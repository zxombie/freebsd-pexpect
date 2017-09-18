#!/usr/bin/env python3

# Copyright (c) 2017 Andrew Turner
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

import argparse
import expect_runner
import pexpect
import sys

key_delay = 0

class Stage:
    def __init__(self, enabled = False, state = None):
        if state is None:
            self.state = expect_runner.State(enabled)
        else:
            self.state = state


class CommandStage(Stage):
    def __init__(self, prompt):
        super().__init__(
          state = expect_runner.CommandState(prompt, enabled = False,
           delay = key_delay))

    def set_next_stage(self, stage):
        self.state.set_next_state(stage.state)

class EarlyBoot(Stage):
    def __init__(self):
        super().__init__(True)
        self.loader = expect_runner.Pattern(
          'to boot immediately, or any other key for command prompt.')
        self.loader.add_action(expect_runner.SendAction(' '))
        self.state.add_pattern(self.loader)

    def set_next_stage(self, stage):
        self.loader.add_action(expect_runner.ChangeStateAction(
            disable = [self.state], enable = [stage.state]))

class Loader(Stage):
    def __init__(self):
        super().__init__(
          state = expect_runner.CommandState('OK', enabled = False,
           delay = key_delay))
        self.state.add_late_command('boot')

    def add_command(self, cmd):
        self.state.add_command(cmd)

    def set_next_stage(self, stage):
        self.state.set_next_state(stage.state)

class Boot(Stage):
    def __init__(self):
        super().__init__(True)
        self.state.add_pattern(expect_runner.Pattern(
          'FreeBSD is a registered trademark of The FreeBSD Foundation.'))
        self.state.add_pattern(expect_runner.Pattern(
            'Trying to mount root from'))
        self.state.add_pattern(expect_runner.Pattern('Feeding entropy'))
        self.state.add_pattern(expect_runner.Pattern('Starting'))

        self.login = expect_runner.Pattern('login:')
        self.login.add_action(expect_runner.SendlineAction('root', key_delay))
        self.state.add_pattern(self.login)

    def set_next_stage(self, stage):
        self.login.add_action(expect_runner.ChangeStateAction(
            disable = [self.state], enable = [stage.state]))

class Shutdown(CommandStage):
    def __init__(self, prompt = 'root@.*#'):
        super().__init__(prompt)
        self.state.add_command('shutdown -p now')

        # Check if we rebooted rather than shutdown.
        # Some UEFI firmware images fail to shutdown correctly.
        p = expect_runner.Pattern('Booting Trusted Firmware')
        p.add_action(expect_runner.ExitAction(0))
        self.state.add_pattern(p)

class FBSDTests(CommandStage):
    def __init__(self):
        super().__init__('root@.*#')
        self.state.add_command('mount -t msdosfs /dev/vtbd1 /mnt')
        self.state.add_command('cd /usr/tests')
        self.state.add_command('kyua test')
        self.state.add_pattern(expect_runner.Pattern('.*->'))
        self.state.add_pattern(expect_runner.Pattern('GEOM_ELI'))
        self.state.add_command('kyua report-junit --output=/mnt/output.xml')
        self.state.add_command('umount /mnt')

    def set_next_stage(self, stage):
        self.state.set_next_state(stage.state)

class FreeBSD:
    def __init__(self):
        self.runner = expect_runner.Runner()
        self.state = expect_runner.State()
        self.stages = []

        # Background state
        p = expect_runner.Pattern('Uptime:.*$')
        p.add_action(expect_runner.ExitAction(0))
        self.state.add_pattern(p)

        p = expect_runner.Pattern('Please press any key to reboot.')
        p.add_action(expect_runner.ExitAction(0))
        self.state.add_pattern(p)

        p = expect_runner.Pattern(pexpect.EOF)
        p.add_action(expect_runner.ExitAction(0))
        self.state.add_pattern(p)

        p = expect_runner.Pattern("KDB: enter: panic")
        p.add_action(expect_runner.ExitAction(1))
        self.state.add_pattern(p)

        p = expect_runner.Pattern(pexpect.TIMEOUT)
        p.add_action(expect_runner.ExitAction(1))
        self.state.add_pattern(p)

        self.runner.add_state(self.state)

    def add_stage(self, stage):
        try:
            last = self.stages[-1]
            last.set_next_stage(stage)
        except IndexError:
            pass
        self.runner.add_state(stage.state)
        self.stages.append(stage)

    def run(self, cmd):
        self.runner.run(cmd)

parser = argparse.ArgumentParser()
parser.add_argument('--key-delay', type = float, default = 0.0,
  help = 'Delay between each key press')
parser.add_argument('--loader', action='append',
  help = 'Run a command at the loader prompt')
parser.add_argument("--tests", help = "Run the FreeBSD test suite",
  action = "store_true")
parser.add_argument("command", help = "VM command to run")
args = parser.parse_args()

key_delay = args.key_delay

fbsd = FreeBSD()
if args.loader != None and len(args.loader) > 0:
    fbsd.add_stage(EarlyBoot())
    loader = Loader()
    for cmd in args.loader:
        loader.add_command(cmd)
    fbsd.add_stage(loader)
fbsd.add_stage(Boot())
if args.tests:
    fbsd.add_stage(FBSDTests())
fbsd.add_stage(Shutdown())

#fbsd.run('qemu-system-aarch64 -m 1024M -cpu cortex-a57 -M virt -bios /home/at718/QEMU_EFI.fd -serial stdio -nographic -monitor none -drive if=none,file=disk-arm64.img,id=hd0 -device virtio-blk-device,drive=hd0 -snapshot')
fbsd.run(args.command)
