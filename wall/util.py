# Wall

# Python forward compatibility
from __future__ import (division, absolute_import, print_function,
    unicode_literals)

import sys
import json
from urllib import urlencode
from collections import Mapping
from weakref import WeakValueDictionary
from tornado.httpclient import AsyncHTTPClient
from redis import StrictRedis

class WebAPI(object):
    class Object(object):
        def __init__(self, dict={}, **kwargs):
            self.__dict__.update(dict)
            self.__dict__.update(kwargs)

        def __str__(self):
            return str(vars(self))
        __repr__ = __str__

    def __init__(self, url, default_args={}, verbose=False):
        self.url = url
        self.default_args = default_args
        self.verbose = verbose

    def call(self, url, args={}, callback=None, method='GET'):
        url = self.url + url
        args = dict(self.default_args.items() + args.items())

        if method == 'GET':
            url = url + '?' + urlencode(args)
            data = None
        elif method == 'POST':
            data = urlencode(args)
        else:
            raise ValueError('method')

        if self.verbose:
            print(method, url, file=sys.stderr)
            print('data:', data, file=sys.stderr)

        def cb(response):
            # TODO: handle errors
            if self.verbose:
                print(response.code, file=sys.stderr)
                print('data:', response.body, file=sys.stderr)
            if callback:
                callback(json.load(response.buffer, object_hook=WebAPI.Object))
        AsyncHTTPClient().fetch(url, cb, method=method, body=data)

class EventTarget(object):
    """
    Event target.

    Inspired by the DOM specification (see
    http://dom.spec.whatwg.org/#interface-eventtarget ).
    """

    def __init__(self):
        self._event_listeners = {}

    def add_event_listener(self, type, listener):
        if type not in self._event_listeners:
            self._event_listeners[type] = set()
        self._event_listeners[type].add(listener)

    def remove_event_listener(self, type, listener):
        try:
            self._event_listeners.get(type, set()).remove(listener)
        except KeyError:
            raise ValueError('listener_unknown')

    def dispatch_event(self, event):
        event.target = self
        for listener in self._event_listeners.get(event.type, set()):
            listener(event)

class Event(object):
    def __init__(self, type, args={}, **kwargs):
        self.type = type
        self.target = None
        self.args = dict(args.items() + kwargs.items())

    def __str__(self):
        return '<{} {} from {}>'.format(self.__class__.__name__, self.type,
            self.target)
    __repr__ = __str__

class ObjectRedis(object):
    """
    Extended Redis client, which additionally provides object-oriented
    operations and object caching.

    Objects are represented as hashes in the Redis database. The translation
    from a hash to an object is carried out by a given `decode` function.

    When `caching` is enabled, objects loaded from the Redis database are cached
    and subsequently retrieved from the cache. An object stays in the cache as
    long as there is a reference to it and it is automatically removed when the
    Python interpreter destroys it. Thus, it is guaranteed that getting the same
    key multiple times will yield the identical object.

    Attributes:

     * `r`: Underlying Redis client. Read-Only.
     * `decode`: function, which decodes an object from a Redis hash. It is
       called with the hash (a `dict`) as single argument. Read-Only.
     * `caching`: switch to enable / disable object caching.
    """
    # TODO: add oset and omset

    def __init__(self, r, decode, caching=True):
        self.r = r
        self.decode = decode
        self.caching = caching
        self._cache = WeakValueDictionary()

    def oget(self, key):
        """
        Get the object for `key`.
        """
        object = self._cache.get(key) if self.caching else None
        if not object:
            hash = self.hgetall(key)
            if hash:
                object = self.decode(hash)
                if self.caching:
                    self._cache[key] = object
        return object

    def omget(self, keys):
        """
        Get the objects for all specified `keys`.
        """
        # TODO: make atomic
        return [self.oget(k) for k in keys]

    def __getattr__(self, name):
        return getattr(self.r, name)

class RedisContainer(Mapping):
    def __init__(self, r, set_key):
        self.r = r
        self.set_key = set_key

    def keys(self):
        return list(self.r.smembers(self.set_key))

    def __getitem__(self, key):
        if key not in self:
            raise KeyError()
        return self.r.oget(key)

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return self.r.scard(self.set_key)

    def __contains__(self, item):
        return self.r.sismember(self.set_key, item)

    def __str__(self):
        return str(dict(self))
    __repr__ = __str__

class Pool(object):
    """
    Utility for keeping track of a pool of asynchronous tasks. A callback is
    executed when all tasks are done.

    Properties:

     * tasks: list of running tasks
     * callback: called when all tasks are done
    """

    def __init__(self, tasks, callback):
        self.tasks = list(tasks)
        self.callback = callback
        if self.done():
            self.callback()

    def done(self):
        return not self.tasks

    def finish(self, task):
        self.tasks.remove(task)
        if self.done():
            self.callback()

def truncate(s, length=64, ellipsis='\u2026'):
    if len(s) > length:
        return s[:length - len(ellipsis)] + ellipsis
    else:
        return s

# ==== Tests ====

from unittest import TestCase

class EventTargetTest(TestCase):
    class Ship(EventTarget):
        def fire(self, weapon):
            self.dispatch_event(Event('fired', weapon=weapon))

    def setUp(self):
        super(EventTargetTest, self).setUp()
        self.ship = EventTargetTest.Ship()
        self.ship.add_event_listener('fired', self.fired)
        self.dispatched_event = None

    def test_remove_event_listener(self):
        self.ship.remove_event_listener('fired', self.fired)
        self.ship.fire('plasma')
        self.assertFalse(self.dispatched_event)

    def test_remove_event_listener_unknown(self):
        with self.assertRaises(ValueError):
            self.ship.remove_event_listener('fired', lambda e: e)

    def test_dispatch_event(self):
        self.ship.fire('plasma')
        self.assertTrue(self.dispatched_event)
        self.assertEqual(self.dispatched_event.target, self.ship)
        self.assertEqual(self.dispatched_event.args['weapon'], 'plasma')

    def fired(self, event):
        self.dispatched_event = event

class ObjectRedisTest(TestCase):
    class Ship(object):
        def __init__(self, id, type):
            self.id = id
            self.type = type

    @staticmethod
    def decode(hash):
        return ObjectRedisTest.Ship(**hash)

    def setUp(self):
        self.r = ObjectRedis(StrictRedis(db=15), self.decode)
        self.r.flushdb()

        self.objects = {
            'ship:0': ObjectRedisTest.Ship('ship:0', 'starfury'),
            'ship:1': ObjectRedisTest.Ship('ship:1', 'frazi')
        }
        for key, object in self.objects.items():
            self.r.hmset(key, vars(object))

    def test_oget(self):
        ship = self.r.oget('ship:0')
        same = self.r.oget('ship:0')
        self.assertIsInstance(ship, ObjectRedisTest.Ship)
        self.assertEqual(vars(self.objects['ship:0']), vars(ship))
        self.assertEqual(id(ship), id(same))

    def test_oget_destroyed_object(self):
        ship = self.r.oget('ship:0')
        destroyed_uid = id(ship)
        del ship
        ship = self.r.oget('ship:0')
        self.assertNotEqual(destroyed_uid, id(ship))

    def test_oget_caching_disabled(self):
        self.r.caching = False
        ship = self.r.oget('ship:0')
        same = self.r.oget('ship:0')
        self.assertNotEqual(id(ship), id(same))

    def test_omget(self):
        ships = self.r.omget(self.objects.keys())
        self.assertEqual(len(self.objects), len(ships))
        for a, b in zip(self.objects.values(), ships):
            self.assertEqual(vars(a), vars(b))

class RedisContainerTest(TestCase):
    def setUp(self):
        self.r = ObjectRedis(StrictRedis(db=15), ObjectRedisTest.decode)
        self.r.flushdb()

        self.objects = {
            'ship:0': ObjectRedisTest.Ship('ship:0', 'starfury'),
            'ship:1': ObjectRedisTest.Ship('ship:1', 'frazi')
        }
        for key, object in self.objects.items():
            self.r.hmset(key, vars(object))
            self.r.sadd('ships', key)

        self.ships = RedisContainer(self.r, 'ships')

    def test_keys(self):
        self.assertEqual(self.objects.keys(), self.ships.keys())

    def test_getitem(self):
        self.assertEqual(vars(self.objects['ship:0']),
            vars(self.ships['ship:0']))

    def test_len(self):
        self.assertEqual(len(self.objects), len(self.ships))

    def test_contains(self):
        self.assertTrue('ship:0' in self.ships)
        self.assertFalse('foo' in self.ships)
