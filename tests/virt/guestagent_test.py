#
# Copyright 2012-2017 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301  USA
#
# Refer to the README and COPYING files for full details of the license
#

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from collections import namedtuple
import json
import logging
import timeit

import six

from vdsm.virt import guestagent
from vdsm.virt import qemuguestagent

from monkeypatch import MonkeyPatchScope
from testlib import VdsmTestCase as TestCaseBase
from testlib import expandPermutations, permutations
from testValidation import slowtest

_MSG_TYPES = ['heartbeat', 'host-name', 'os-version',
              'network-interfaces', 'applications', 'disks-usage']

_INPUTS = [
    {'free-ram': 1024000,
     'memory-stat': {'swap_out': 0, 'majflt': 0, 'mem_free': 4466104,
                     'swap_in': 0, 'pageflt': 0, 'mem_total': 8059320,
                     'mem_unused': 2733832}},

    {'name': 'example.ovirt.org'},
    {'version': '2.6.32-71.el6.x86_64'},

    {'interfaces': [
        {'hw': '00:21:cc:68:d7:38', 'name': 'eth0', 'inet':
            ['9.115.122.77'], 'inet6': ['fe80::221:ccff:fe68:d738']},
        {'hw': 'a0:88:b4:f0:ce:a0', 'name': 'wlan0', 'inet':
            ['9.115.126.23'], 'inet6': ['fe80::a288:b4ff:fef0:cea0']},
        {'hw': '52:54:00:5b:3f:e1', 'name': 'virbr0', 'inet':
            ['192.168.122.1'], 'inet6': []}]},

    {'applications':
        ['kernel-2.6.32-71.7.1.el6', 'kernel-2.6.32-220.el6']},

    {'disks': [
        {'total': 130062397440, 'path': '/', 'fs': 'ext4',
            'used': 76402614272},
        {'total': 203097088, 'path': '/boot', 'fs': 'ext4',
            'used': 153149440}]}]

_OUTPUTS = [
    {'memUsage': 1024000, 'memoryStats':
        {'swap_out': '0', 'majflt': '0', 'mem_free':
            '2733832', 'swap_in': '0', 'pageflt': '0',
            'mem_total': '8059320', 'mem_unused': '2733832'}},

    {'guestName': 'example.ovirt.org'},
    {'guestOs': '2.6.32-71.el6.x86_64'},

    {'netIfaces': [
        {'hw': '00:21:cc:68:d7:38', 'name': 'eth0', 'inet':
            ['9.115.122.77'], 'inet6': ['fe80::221:ccff:fe68:d738']},
        {'hw': 'a0:88:b4:f0:ce:a0', 'name': 'wlan0', 'inet':
            ['9.115.126.23'], 'inet6': ['fe80::a288:b4ff:fef0:cea0']},
        {'hw': '52:54:00:5b:3f:e1', 'name': 'virbr0', 'inet':
            ['192.168.122.1'], 'inet6': []}],
        'guestIPs': '9.115.122.77 9.115.126.23 192.168.122.1'},

    {'appsList':
        ('kernel-2.6.32-71.7.1.el6', 'kernel-2.6.32-220.el6',)},

    {'disksUsage': [
        {'total': '130062397440', 'path': '/', 'fs': 'ext4',
            'used': '76402614272'},
        {'total': '203097088', 'path': '/boot', 'fs': 'ext4',
            'used': '153149440'}]}]


# do not use permutations here: otherwise pytest with python3 will
# fail to set up the test environment, because we need to use the C locale,
# thus the test name will contain bad utf-8 data.
class TestFiltering(TestCaseBase):

    def test_filter_xml_chars_valid(self):
        for value in [
            u"\u0009 \u000a",
            u"\u000d",
            u"\u0020 \u007e",
            u"\u0085",
            u"\u00a0 \ud7ff",
            u"\ue000 \ufffd",
            u"\U00010000 \U0010ffff",
        ]:
            self.assertEqual(value, guestagent._filterXmlChars(value))

    def test_filter_xml_chars_invalid(self):
        for value in [
            u"\u0000 \u0008",
            u"\u000b \u000c",
            u"\u000e \u001f",
            u"\u007f \u0084",
            u"\u0086 \u009f",
            u"\ud800 \udfff",
            u"\ufffe \uffff",
        ]:
            self.assertEqual(
                u'\ufffd \ufffd', guestagent._filterXmlChars(value))

    @slowtest
    def test_filter_xml_chars_timing(self):
        setup = ('from vdsm.virt.guestagent import _filterXmlChars;'
                 'x = u"x" * 1024 * 1024')
        elapsed = timeit.timeit('_filterXmlChars(x)', setup=setup, number=10)
        print(elapsed, "seconds")

    def test_filter_object_dict(self):
        raw = {u"a\x00": u"b\x01", u"c\x02": u"d\x03"}
        filtered = {u"a\ufffd": u"b\ufffd", u"c\ufffd": u"d\ufffd"}
        self.assertEqual(filtered, guestagent._filterObject(raw))

    def test_filter_object_nested_dict(self):
        raw = {u"a\x00": {u"b\x01": {u"c\x02": u"d\x03"}}}
        filtered = {u"a\ufffd": {u"b\ufffd": {u"c\ufffd": u"d\ufffd"}}}
        self.assertEqual(filtered, guestagent._filterObject(raw))

    def test_filter_object_list(self):
        raw = [u"a\x00", u"b\x01", u"c\x02", u"d\x03"]
        filtered = [u"a\ufffd", u"b\ufffd", u"c\ufffd", u"d\ufffd"]
        self.assertEqual(filtered, guestagent._filterObject(raw))

    def test_filter_object_nested_lists(self):
        raw = [u"a\x00", [u"b\x01", [u"c\x02", u"d\x03"]]]
        filtered = [u"a\ufffd", [u"b\ufffd", [u"c\ufffd", u"d\ufffd"]]]
        self.assertEqual(filtered, guestagent._filterObject(raw))

    def test_filter_object_nested_mix(self):
        raw = {u"a\x00": [u"b\x01", {u"c\x02": u"d\x03"}]}
        filtered = {u"a\ufffd": [u"b\ufffd", {u"c\ufffd": u"d\ufffd"}]}
        self.assertEqual(filtered, guestagent._filterObject(raw))

    def test_filter_object_other_types(self):
        raw = {u"int": 1,
               u"float": 3.14,
               u"true": True,
               u"false": False,
               u"none": None}
        self.assertEqual(raw, guestagent._filterObject(raw))

    @slowtest
    def test_filter_object_timing(self):
        setup = """
from vdsm.virt.guestagent import _filterObject
d = {u'netIfaces': [
        {
            u'hw': u'00:21:cc:68:d7:38',
            u'name': u'eth0',
            u'inet': [u'9.115.122.77'],
            u'inet6': [u'fe80::221:ccff:fe68:d738']
        },
        {
            u'hw': u'a0:88:b4:f0:ce:a0',
            u'name': u'wlan0',
            u'inet': [u'9.115.126.23'],
            u'inet6': [u'fe80::a288:b4ff:fef0:cea0']
        },
        {
            u'hw': u'52:54:00:5b:3f:e1',
            u'name': u'virbr0',
            u'inet': [u'192.168.122.1'],
            u'inet6': []
        }
    ],
    u'guestIPs': u'9.115.122.77 9.115.126.23 192.168.122.1'
}
"""
        elapsed = timeit.timeit('_filterObject(d)', setup=setup, number=1000)
        print(elapsed, "seconds")


class TestGuestIF(TestCaseBase):

    def test_handleMessage(self):
        fakeGuestAgent = guestagent.GuestAgent(None, None, self.log,
                                               lambda: None, lambda: None,
                                               lambda: None)
        testCase = namedtuple('testCase', 'msgType, message, assertDict')

        for t in zip(_MSG_TYPES, _INPUTS, _OUTPUTS):
            t = testCase(*t)
            fakeGuestAgent._handleMessage(t.msgType, t.message)
            for (k, v) in six.iteritems(t.assertDict):
                self.assertEqual(fakeGuestAgent.guestInfo[k], v)

    def test_guestinfo_encapsulation(self):
        fake_guest_agent = guestagent.GuestAgent(None, None, self.log,
                                                 lambda: None, lambda: None,
                                                 lambda: None)
        fake_guest_agent._handleMessage(_MSG_TYPES[0], _INPUTS[0])
        with MonkeyPatchScope([
                (fake_guest_agent, 'isResponsive', lambda: True)
        ]):
            guest_info = fake_guest_agent.getGuestInfo()
            for k in _OUTPUTS[0]:
                value = guest_info[k]
                if isinstance(value, list):
                    value.append('modified')
                elif isinstance(value, dict):
                    value['modified'] = 'modified'
                else:
                    value = 'modified'
                guest_info[k] = value
            guest_info = fake_guest_agent.getGuestInfo()
            for (k, v) in six.iteritems(_OUTPUTS[0]):
                self.assertEqual(guest_info[k], v)


class TestGuestIFHandleData(TestCaseBase):
    # helper for chunking messages
    def messageChunks(self, s, chunkSize):
        for start in range(0, len(s), chunkSize):
            yield s[start:start + chunkSize]

    # perform general setup tasks
    def setUp(self):
        self.fakeGuestAgent = guestagent.GuestAgent(None, None, self.log,
                                                    lambda: None,
                                                    lambda: None,
                                                    lambda: None)
        self.fakeGuestAgent.MAX_MESSAGE_SIZE = 100
        self.maxMessageSize = self.fakeGuestAgent.MAX_MESSAGE_SIZE
        self.fakeGuestAgent._clearReadBuffer()
        # Guest agent must not be stopped
        self.fakeGuestAgent._stopped = False
        # Copy the defaults of the guest agent -> Not set information
        self.infoDefaults = self.fakeGuestAgent.guestInfo.copy()

    def dataToMessage(self, name, payload):
        payload = payload.copy()
        payload["__name__"] = name
        return json.dumps(payload) + "\n"

    def testBigChunk(self):
        input = ""
        expected = self.infoDefaults

        testCase = namedtuple('testCase', 'msgType, message, assertDict')

        # Building a big blob of data from test inputs
        # and produce the expected outputs from it
        for t in zip(_MSG_TYPES, _INPUTS, _OUTPUTS):
            t = testCase(*t)
            msgStr = self.dataToMessage(t.msgType, t.message)
            input += msgStr
            isOverSize = len(msgStr) > self.maxMessageSize
            for (k, v) in six.iteritems(t.assertDict):
                if not isOverSize:
                    expected[k] = v

        # Performing the test
        for chunk in self.messageChunks(input, (self.maxMessageSize // 2) + 1):
            self.fakeGuestAgent._handleData(chunk.encode('utf-8'))

        for (k, v) in six.iteritems(expected):
            self.assertEqual(self.fakeGuestAgent.guestInfo[k], expected[k])

    def testMixed(self):
        testCase = namedtuple('testCase', 'msgType, message, assertDict')
        for t in zip(_MSG_TYPES, _INPUTS, _OUTPUTS):
            t = testCase(*t)
            msgStr = self.dataToMessage(t.msgType, t.message)
            isOverLimit = len(msgStr) > self.maxMessageSize

            for chunk in self.messageChunks(msgStr, self.maxMessageSize):
                self.fakeGuestAgent._handleData(chunk.encode('utf-8'))
                if chunk[-1] != '\n':
                    self.assertEqual(self.fakeGuestAgent._messageState,
                                     guestagent.MessageState.TOO_BIG)

            # At the end the message state has to be NORMAL again
            self.assertEqual(self.fakeGuestAgent._messageState,
                             guestagent.MessageState.NORMAL)

            for (k, v) in six.iteritems(t.assertDict):
                if isOverLimit:
                    # If the message size was over the allowed limit
                    # the message should contain the default value
                    self.assertEqual(self.fakeGuestAgent.guestInfo[k],
                                     self.infoDefaults[k])
                else:
                    # If the message size was within the allowed range
                    # the message should have been put into the guestInfo dict
                    self.assertEqual(self.fakeGuestAgent.guestInfo[k], v)


class DiskMappingTests(TestCaseBase):

    def setUp(self):
        self.agent = guestagent.GuestAgent(None, None, None, lambda: None,
                                           lambda: None, lambda: None)

    def test_init(self):
        self.assertEqual(self.agent.guestDiskMapping, {})
        self.assertIsNone(self.agent.diskMappingHash)

    def test_change_disk_mapping(self):
        old_hash = self.agent.diskMappingHash
        self.agent.guestDiskMapping = {'/dev/vda': 'xxx'}
        self.assertNotEqual(self.agent.diskMappingHash, old_hash)
        self.assertTrue(isinstance(self.agent.diskMappingHash, int))


class FakeClientIF(object):
    def __init__(self, vmContainer):
        self.vmContainer = vmContainer


@expandPermutations
class QemuGuestAgentTests(TestCaseBase):

    @permutations([
        [set(['vm1', 'vm2']), set(['vm1']), set(['vm2'])],
        [set(['vm1', 'vm2']), set(['vm2']), set(['vm2'])],
        [set(['vm1', 'vm2']), set(['vm1']), set([])]
    ])
    def test_cleanup(self, init_vms, failed_vms, removed_vms):
        capabilities = {'version': 1, 'commands': True}
        vm_container = {vm: True for vm in init_vms}
        cif = FakeClientIF(vm_container)
        log = logging.getLogger('test')
        scheduler = None
        poller = qemuguestagent.QemuGuestAgentPoller(cif, log, scheduler)
        for vm in init_vms:
            poller.update_caps(vm, capabilities)
            poller.update_guest_info(vm, set())
        for vm in failed_vms:
            poller.set_failure(vm)
        for vm in removed_vms:
            del vm_container[vm]
        poller._cleanup()
        for vm in init_vms:
            if vm in removed_vms:
                self.assertIsNone(poller.get_caps(vm))
                self.assertIsNone(poller.get_guest_info(vm))
                self.assertIsNone(poller.last_failure(vm))
            else:
                self.assertIsNotNone(poller.get_caps(vm))
                self.assertIsNotNone(poller.get_guest_info(vm))
                if vm in failed_vms:
                    self.assertIsNotNone(poller.last_failure(vm))
