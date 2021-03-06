
import time
import datetime
import ipaddr
from twisted.trial import unittest
from twisted.internet import reactor
from zope.interface import implements

from txtorcon import Stream, IStreamListener, ICircuitContainer

class FakeCircuit:
    def __init__(self, id=-999):
        self.streams = []
        self.id = id

class Listener(object):
    implements(IStreamListener)
    
    def __init__(self, expected):
        "expect is a list of tuples: (event, {key:value, key1:value1, ..})"
        self.expected = expected

    def checker(self, state, stream, *args):
        if self.expected[0][0] != state:
            raise RuntimeError('Expected event "%s" not "%s".'%(self.expected[0][0], state))
        for (k,v) in self.expected[0][1].items():
            if k == 'args':
                if v != args:
                    raise RuntimeError('Expected argument to have value "%s", not "%s"' % (v, args))
            elif getattr(stream, k) != v:
                raise RuntimeError('Expected attribute "%s" to have value "%s", not "%s"' % (k, v, getattr(stream, k)))
        self.expected = self.expected[1:]
            
    def stream_new(self, stream):
        "a new stream has been created"
        self.checker('new', stream)
    
    def stream_succeeded(self, stream):
        "stream has succeeded"
        self.checker('succeeded', stream)
    
    def stream_attach(self, stream, circuit):
        "the stream has been attached to a circuit"
        self.checker('attach', stream, circuit)

    def stream_detach(self, stream, reason):
        "the stream has been attached to a circuit"
        self.checker('detach', stream, reason)

    def stream_closed(self, stream):
        "stream has been closed (won't be in controller's list anymore)"
        self.checker('closed', stream)

    def stream_failed(self, stream, reason, remote_reason):
        "stream failed for some reason (won't be in controller's list anymore)"
        self.checker('failed', stream, reason, remote_reason)
    

class StreamTests(unittest.TestCase):

    implements(ICircuitContainer)

    def find_circuit(self, id):
        return self.circuits[id]

    def setUp(self):
        self.circuits = {}

    def test_circuit_already_valid_in_new(self):
        stream = Stream(self)
        stream.circuit = FakeCircuit(1)
        stream.update("1 NEW 0 94.23.164.42.$43ED8310EB968746970896E8835C2F1991E50B69.exit:9001 SOURCE_ADDR=(Tor_internal):0 PURPOSE=DIR_FETCH".split())
        errs = self.flushLoggedErrors()
        self.assertTrue(len(errs) == 1)
        self.assertTrue('Weird' in errs[0].getErrorMessage())

    def test_magic_circuit_detach(self):
        stream = Stream(self)
        stream.circuit = FakeCircuit(1)
        stream.circuit.streams = [stream]
        stream.update("1 SENTCONNECT 0 94.23.164.42.$43ED8310EB968746970896E8835C2F1991E50B69.exit:9001 SOURCE_ADDR=(Tor_internal):0 PURPOSE=DIR_FETCH".split())
        self.assertTrue(stream.circuit is None)

    def test_args_in_ctor(self):
        stream = Stream(self)
        stream.update("1 NEW 0 94.23.164.42.$43ED8310EB968746970896E8835C2F1991E50B69.exit:9001 SOURCE_ADDR=(Tor_internal):0 PURPOSE=DIR_FETCH".split())
        self.assertTrue(stream.id == 1)
        self.assertTrue(stream.state == 'NEW')

    def test_parse_resolve(self):
        stream = Stream(self)
        stream.update("1604 NEWRESOLVE 0 www.google.ca:0 PURPOSE=DNS_REQUEST".split())
        self.assertTrue(stream.state == 'NEWRESOLVE')
    
    def test_listener_new(self):
        listener = Listener([('new', {'target_port':9001})])
        
        stream = Stream(self)
        stream.listen(listener)
        stream.update("1 NEW 0 94.23.164.42.$43ED8310EB968746970896E8835C2F1991E50B69.exit:9001 SOURCE_ADDR=(Tor_internal):0 PURPOSE=DIR_FETCH".split())

    def test_listener_attach(self):
        self.circuits[186] = FakeCircuit(186)
        
        listener = Listener([('new', {'target_host':'www.yahoo.com', 'target_port':80}),
                             ('attach', {'target_addr':ipaddr.IPAddress('1.2.3.4')})])
        
        stream = Stream(self)
        stream.listen(listener)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        stream.update("316 REMAP 186 1.2.3.4:80 SOURCE=EXIT".split())

        self.assertTrue(self.circuits[186].streams[0] == stream)
    
    def test_listener_attach_no_remap(self):
        "Attachment is via SENTCONNECT on .onion addresses (for example)"
        self.circuits[186] = FakeCircuit(186)
        
        listener = Listener([('new', {'target_host':'www.yahoo.com', 'target_port':80}),
                             ('attach', {})])
        
        stream = Stream(self)
        stream.listen(listener)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        stream.update("316 SENTCONNECT 186 1.2.3.4:80 SOURCE=EXIT".split())

        self.assertTrue(self.circuits[186].streams[0] == stream)
    
    def test_update_wrong_stream(self):
        self.circuits[186] = FakeCircuit(186)
        
        stream = Stream(self)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        try:
            stream.update("999 SENTCONNECT 186 1.2.3.4:80 SOURCE=EXIT".split())
            self.fail()
        except Exception, e:
            self.assertTrue('wrong stream' in str(e))

    def test_update_illegal_state(self):
        self.circuits[186] = FakeCircuit(186)
        
        stream = Stream(self)
        try:
            stream.update("316 FOO 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
            self.fail()
        except Exception, e:
            self.assertTrue('Unknown state' in str(e))

    def test_listen_unlisten(self):
        self.circuits[186] = FakeCircuit(186)
        
        listener = Listener([])
        
        stream = Stream(self)
        stream.listen(listener)
        stream.unlisten(listener)
        self.assertTrue(len(stream.listeners) == 0)

    def test_stream_changed(self):
        "Change a stream-id mid-stream."
        self.circuits[186] = FakeCircuit(186)
        
        listener = Listener([('new', {'target_host':'www.yahoo.com', 'target_port':80}),
                             ('attach', {}),
                             ('succeeded', {})])
        
        stream = Stream(self)
        stream.listen(listener)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        stream.update("316 SENTCONNECT 186 1.2.3.4:80 SOURCE=EXIT".split())
        self.assertTrue(self.circuits[186].streams[0] == stream)

        # magically change circuit ID without a DETACHED, should fail
        stream.update("316 SUCCEEDED 999 1.2.3.4:80 SOURCE=EXIT".split())
        errs = self.flushLoggedErrors()
        self.assertTrue(len(errs) == 1)
        # kind of fragile to look at strings, but...
        self.assertTrue('186 to 999' in str(errs[0]))
    
    def test_stream_changed_with_detach(self):
        "Change a stream-id mid-stream, but with a DETACHED message"
        self.circuits[123] = FakeCircuit(123)
        self.circuits[456] = FakeCircuit(456)
        
        listener = Listener([('new', {'target_host':'www.yahoo.com', 'target_port':80}),
                             ('attach', {}),
                             ('detach', {'args':('END',)}),
                             ('attach', {})])
        
        stream = Stream(self)
        stream.listen(listener)
        stream.update("999 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        stream.update("999 SENTCONNECT 123 1.2.3.4:80".split())
        self.assertTrue(len(self.circuits[123].streams) == 1)
        self.assertTrue(self.circuits[123].streams[0] == stream)

        stream.update("999 DETACHED 123 1.2.3.4:80 REASON=END REMOTE_REASON=MISC".split())
        self.assertTrue(len(self.circuits[123].streams) == 0)
        
        stream.update("999 SENTCONNECT 456 1.2.3.4:80 SOURCE=EXIT".split())
        self.assertTrue(len(self.circuits[456].streams) == 1)
        self.assertTrue(self.circuits[456].streams[0] == stream)
    
    def test_listener_close(self):
        self.circuits[186] = FakeCircuit(186)
        
        listener = Listener([('new', {'target_host':'www.yahoo.com', 'target_port':80}),
                             ('attach', {'target_addr':ipaddr.IPAddress('1.2.3.4')}),
                             ('closed', {})])
        stream = Stream(self)
        stream.listen(listener)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        stream.update("316 REMAP 186 1.2.3.4:80 SOURCE=EXIT".split())
        stream.update("316 CLOSED 186 1.2.3.4:80 REASON=END REMOTE_REASON=DONE".split())
        
        self.assertTrue(len(self.circuits[186].streams) == 0)
        
    def test_listener_fail(self):
        listener = Listener([('new', {'target_host':'www.yahoo.com', 'target_port':80}),
                             ('attach', {'target_addr':ipaddr.IPAddress('1.2.3.4')}),
                             ('failed', {'args':('TIMEOUT','DESTROYED')})])
        stream = Stream(self)
        stream.listen(listener)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        self.circuits[186] = FakeCircuit(186)
        stream.update("316 REMAP 186 1.2.3.4:80 SOURCE=EXIT".split())
        stream.update("316 FAILED 0 1.2.3.4:80 REASON=TIMEOUT REMOTE_REASON=DESTROYED".split())

    def test_str(self):
        stream = Stream(self)
        stream.update("316 NEW 0 www.yahoo.com:80 SOURCE_ADDR=127.0.0.1:55877 PURPOSE=USER".split())
        stream.circuit = FakeCircuit(1)
        s = str(stream)

    def test_ipv6(self):
        listener = Listener([('new', {'target_host':'::1', 'target_port':80})])

        stream = Stream(self)
        stream.listen(listener)
        stream.update("1234 NEW 0 ::1:80 SOURCE_ADDR=127.0.0.1:57349 PURPOSE=USER".split())

    def test_ipv6_remap(self):
        stream = Stream(self)
        stream.update("1234 REMAP 0 ::1:80 SOURCE_ADDR=127.0.0.1:57349 PURPOSE=USER".split())
        self.assertTrue(stream.target_addr == ipaddr.IPAddress('::1'))

    def test_ipv6_source(self):
        listener = Listener([('new', {'source_addr':ipaddr.IPAddress('::1'), 'source_port':12345})])

        stream = Stream(self)
        stream.listen(listener)
        stream.update("1234 NEW 0 127.0.0.1:80 SOURCE_ADDR=::1:12345 PURPOSE=USER".split())

    def test_states_and_uris(self):
        self.circuits[1] = FakeCircuit(1)
        
        stream = Stream(self)
        for address in ['1.2.3.4:80',
                        '1.2.3.4.315D5684D5343580D409F16119F78D776A58AEFB.exit:80',
                        'timaq4ygg2iegci7.onion:80']:
            
            line = "316 %s 1 %s REASON=FOO"
            for state in ['NEW', 'SUCCEEDED', 'REMAP',
                          'SENTCONNECT',
                          'DETACHED', 'NEWRESOLVE', 'SENTRESOLVE',
                          'FAILED', 'CLOSED']:
                stream.update((line % (state, address)).split(' '))
                self.assertTrue(stream.state == state)
