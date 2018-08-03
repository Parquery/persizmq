#!/usr/bin/env python3

# pylint: disable=missing-docstring,too-many-public-methods
import pathlib
import shutil
import tempfile
import time
import unittest
import uuid
from typing import List, Optional  # pylint: disable=unused-import

import zmq

import persizmq
import persizmq.filter


class TestContext:
    def __init__(self, base_url: str = "inproc://persizmq_test") -> None:
        self.url = base_url + str(uuid.uuid4())
        self.context = zmq.Context()
        self.publisher = self.context.socket(zmq.PUB)  # pylint: disable=no-member
        self.subscribers = []  # type: List[zmq.Socket]
        self.tmp_dir = None  # type: Optional[pathlib.Path]

    def subscriber(self) -> zmq.Socket:
        """
        Creates a new subscriber that listens to whatever the publisher of this instance
        publishes.

        The subscriber will be closed by this instance.

        :return: zmq subscriber
        """
        subscriber = self.context.socket(zmq.SUB)  # pylint: disable=no-member
        self.subscribers.append(subscriber)

        subscriber.setsockopt_string(zmq.SUBSCRIBE, "")  # pylint: disable=no-member
        subscriber.connect(self.url)

        return subscriber

    def __enter__(self):
        self.tmp_dir = pathlib.Path(tempfile.mkdtemp())
        self.publisher.bind(self.url)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for subscriber in self.subscribers:
            subscriber.close()

        shutil.rmtree(self.tmp_dir.as_posix())
        self.publisher.close()
        self.context.term()


class TestThreadedSubscriber(unittest.TestCase):
    def test_operational(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=lambda msg: None, subscriber=subscriber, on_exception=lambda exc: None)

                # Threaded subscriber is already operational after the constructor.
                self.assertTrue(thread_sub.operational)
                with thread_sub:
                    self.assertTrue(thread_sub.operational)

                # Threaded subscriber is not operational after exiting the context.
                self.assertFalse(thread_sub.operational)

    def test_a_message(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:

                class Helper:
                    def __init__(self):
                        self.msg_received = None

                    def callback(self, msg: bytes):
                        self.msg_received = msg

                helper = Helper()

                thread_sub = persizmq.ThreadedSubscriber(
                    callback=helper.callback, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    ctx.publisher.send(b"0001")
                    time.sleep(0.01)

                    self.assertEqual(b"0001", helper.msg_received)

    def test_exception(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:

                def callback(msg: bytes) -> None:  # pylint: disable=unused-argument
                    raise Exception("Here I come!")

                exception = None

                def on_exception(exc):
                    nonlocal exception
                    exception = exc

                thread_sub = persizmq.ThreadedSubscriber(
                    callback=callback, subscriber=subscriber, on_exception=on_exception)

                with thread_sub:
                    ctx.publisher.send(b"0002")
                    time.sleep(0.01)

                    self.assertIsNotNone(exception)
                    self.assertEqual("Here I come!", str(exception))


class TestPersistentSubscriber(unittest.TestCase):
    def test_no_message_received(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)
                with thread_sub:
                    msg = storage.front()
                    self.assertIsNone(msg)
                    self.assertFalse(storage.pop_front())

    def test_a_message(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    ctx.publisher.send(b"1984")

                    time.sleep(0.01)

                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1984", msg)
                    self.assertTrue(storage.pop_front())

                    msg = storage.front()
                    self.assertIsNone(msg)
                    self.assertFalse(storage.pop_front())

    def test_multiple_messages(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    # publish a message
                    ctx.publisher.send(b"1985")

                    time.sleep(0.01)

                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1985", msg)
                    self.assertTrue(storage.pop_front())

                    msg = storage.front()
                    self.assertIsNone(msg)
                    self.assertFalse(storage.pop_front())

                    # publish two in a row
                    ctx.publisher.send(b"1986")
                    ctx.publisher.send(b"1987")

                    time.sleep(0.01)

                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1986", msg)

                    # ask for the same front
                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1986", msg)
                    self.assertTrue(storage.pop_front())

                    # publish a third one
                    ctx.publisher.send(b"1988")

                    time.sleep(0.01)

                    # check the second one
                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1987", msg)
                    self.assertTrue(storage.pop_front())

                    # check the third one
                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1988", msg)
                    self.assertTrue(storage.pop_front())

    def test_persistency(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    # publish a message
                    ctx.publisher.send(b"1985")

                    time.sleep(0.01)

            # simulate a restart
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"1985", msg)
                    self.assertTrue(storage.pop_front())

                    msg = storage.front()
                    self.assertIsNone(msg)
                    self.assertFalse(storage.pop_front())

    def test_order(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    # Make sure the correct order is kept even for a lot of messages.
                    for i in range(2000, 2020):
                        ctx.publisher.send("{}".format(i).encode())
                        time.sleep(0.01)

            # simulate a restart
            with ctx.subscriber() as subscriber:
                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir.as_posix())
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=storage.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    for i in range(2000, 2020):
                        msg = storage.front()
                        self.assertIsNotNone(msg)
                        assert isinstance(msg, bytes)
                        self.assertEqual("{}".format(i).encode(), msg)
                        self.assertTrue(storage.pop_front())


class TestFilters(unittest.TestCase):
    def test_that_it_works(self):
        # pylint: disable=too-many-statements
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                pers_dir_filter = ctx.tmp_dir / 'filter'

                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir)
                thread_sub = persizmq.ThreadedSubscriber(
                    subscriber=subscriber, callback=lambda msg: None, on_exception=lambda exc: None)
                thread_sub.callback = \
                    lambda msg: storage.add_message(
                        persizmq.filter.MinPeriod(min_period=1, persistent_dir=pers_dir_filter)(msg))

                with thread_sub:
                    # Send two messages.
                    ctx.publisher.send(b"3000")
                    ctx.publisher.send(b"3001")

                    time.sleep(0.01)

                    # Make sure only one arrived.
                    msg = storage.front()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"3000", msg)
                    self.assertTrue(storage.pop_front())

                    msg = storage.front()
                    self.assertIsNone(msg)

                # Rebuild the persistent subscriber.
                del storage
                del thread_sub

                storage = persizmq.PersistentStorage(persistent_dir=ctx.tmp_dir)
                thread_sub = persizmq.ThreadedSubscriber(
                    subscriber=subscriber, callback=lambda msg: None, on_exception=lambda exc: None)
                thread_sub.callback = lambda msg: storage.add_message(
                    persizmq.filter.MinPeriod(min_period=10, persistent_dir=pers_dir_filter)(msg))

                with thread_sub:
                    # Send one message and make sure that the last timestamp was correctly loaded
                    # (the new message must be rejected).
                    ctx.publisher.send(b"3002")

                    time.sleep(0.01)

                    msg = storage.front()
                    self.assertIsNone(msg)

                    thread_sub.callback = lambda msg: storage.add_message(persizmq.filter.MaxSize(max_size=1000)(msg))

                    # Generate a too large message and check that it is rejected.
                    ctx.publisher.send(b"x" * 1001)
                    time.sleep(0.01)

                    msg = storage.front()
                    self.assertIsNone(msg)


class TestPersistentLatest(unittest.TestCase):
    def test_that_it_works(self):
        with TestContext() as ctx:
            with ctx.subscriber() as subscriber:
                persi_latest = persizmq.PersistentLatestStorage(persistent_dir=ctx.tmp_dir)
                thread_sub = persizmq.ThreadedSubscriber(
                    callback=persi_latest.add_message, subscriber=subscriber, on_exception=lambda exc: None)

                with thread_sub:
                    # Make sure only the newest one is kept.
                    self.assertFalse(persi_latest.new_message)

                    ctx.publisher.send(b"4000")
                    time.sleep(0.01)

                    self.assertTrue(persi_latest.new_message)

                    ctx.publisher.send(b"4001")
                    time.sleep(0.01)

                    self.assertTrue(persi_latest.new_message)

                    msg = persi_latest.message()

                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"4001", msg)
                    self.assertFalse(persi_latest.new_message)

                    # The same for lots of messages.
                    for i in range(4010, 4020):
                        ctx.publisher.send("{}".format(i).encode())
                        time.sleep(0.01)

                    msg = persi_latest.message()
                    self.assertIsNotNone(msg)
                    assert isinstance(msg, bytes)
                    self.assertEqual(b"4019", msg)
                    self.assertFalse(persi_latest.new_message)


if __name__ == '__main__':
    unittest.main()
