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

import pexpect
import sys
import time

def _sendline_delay(child, line, delay):
    if delay > 0:
        for ch in line:
            child.send(ch)
            time.sleep(delay)
        child.sendline('')
    else:
        child.sendline(line)

class Action:
    def run(self, child):
        pass

class ExitAction(Action):
    def __init__(self, code):
        self.code = code

    def run(self, child):
        sys.exit(self.code)

class ChangeStateAction(Action):
    def __init__(self, enable = None, disable = None):
        self.enable = enable
        self.disable = disable

    def run(self, child):
        if self.enable is not None:
            for state in self.enable:
                state.set_enabled(True)

        if self.disable is not None:
            for state in self.disable:
                state.set_enabled(False)

class SendAction(Action):
    def __init__(self, line):
        self.line = line

    def run(self, child):
        child.send(self.line)

class SendlineAction(Action):
    def __init__(self, line, delay = 0):
        self.delay = delay
        self.line = line

    def run(self, child):
        _sendline_delay(child, self.line, self.delay)


class Pattern:
    def __init__(self, pattern):
        self.pattern = pattern
        self.actions = []

    def add_action(self, action):
        self.actions.append(action)

    def run(self, child):
        for act in self.actions:
            act.run(child)


class State:
    def __init__(self, enabled = True):
        self.enabled = enabled
        self.patterns = []

    def add_pattern(self, pattern):
        self.patterns.append(pattern)

    def set_enabled(self, enabled):
        self.enabled = enabled

class _CommandAction(Action):
    def __init__(self, runner, next_state, delay = 0):
        self.commands = []
        self.late_commands = []
        self.idx = 0
        self.delay = delay

        self.runner = runner
        self.next_state = next_state

    def add_command(self, command):
        self.commands.append(command)

    def add_late_command(self, command):
        self.late_commands.append(command)

    def set_next_state(self, next_state):
        self.next_state = next_state

    def run(self, child):
        num_cmds = len(self.commands)
        num_late_cmds = len(self.late_commands)
        if self.idx < num_cmds:
            _sendline_delay(child, self.commands[self.idx], self.delay)
            self.idx += 1
        elif self.idx < (num_cmds + num_late_cmds):
            _sendline_delay(child, self.late_commands[self.idx - num_cmds],
              self.delay)
            self.idx += 1
        if self.idx == (num_cmds + num_late_cmds):
            self.runner.set_enabled(False)
            if self.next_state is not None:
                self.next_state.set_enabled(True)

class CommandState(State):
    def __init__(self, prompt, enabled = True, next_state = None, delay = 0):
        super().__init__(enabled)
        self.prompt = prompt
        self.pat = Pattern(prompt)

        self.action = _CommandAction(self, next_state, delay)
        self.pat.add_action(self.action)

        self.add_pattern(self.pat)

    def add_command(self, command):
        self.action.add_command(command)

    def add_late_command(self, command):
        self.action.add_late_command(command)

    def set_next_state(self, state):
        self.action.set_next_state(state)

class Runner:
    def __init__(self):
        self.states = []

    def add_state(self, state):
        self.states.append(state)

    def match(self, child):
        matches = []
        patterns = []

        for state in self.states:
            if not state.enabled:
                continue

            for pat in state.patterns:
                matches.append(pat.pattern)
                patterns.append(pat)

        i = child.expect(matches, timeout = 3660)
        pat = patterns[i]
        pat.run(child)

    def run(self, cmd):
        child = pexpect.spawnu(cmd)
        child.logfile = sys.stdout

        while True:
            self.match(child)
