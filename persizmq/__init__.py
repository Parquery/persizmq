#!/usr/bin/env python3
"""
provides persistence to zeromq.
"""
import contextlib
import copy
import pathlib
import threading
import time
from typing import List, Optional, Callable, Union  # pylint: disable=unused-import

import zmq


class ThreadedSubscriber:
    """
    takes a subscriber and listens in a separate thread for messages. Communicates the message to the outside through
    a callback. Locking should be considered by the callback provider.

    Do not share the sockets between threads, see http://zguide.zeromq.org/py:chapter2#Multithreading-with-ZeroMQ
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(self, subscriber: zmq.Socket, callback: Callable[[bytes], None],
                 on_exception: Callable[[Exception], None]) -> None:
        """
        :param subscriber: zeromq subscriber socket; only operated by ThreadedSubscriber, do not share among threads!
        :param callback:
            This function is called every time a message is received. Can be accessed and changed later
            through ThreadedSubscriber.callback
        :param on_exception: Is called when an exception occurs during the callback call.
        """

        if isinstance(subscriber, zmq.Socket):
            self._subscriber = subscriber
        else:
            raise TypeError("unexpected type of the argument socket: {}".format(subscriber.__class__.__name__))

        self.callback = callback
        self.on_expection = on_exception
        self.operational = False

        self._exit_stack = contextlib.ExitStack()

        init_err = None  # type: Optional[Exception]

        try:
            # control structures
            self._context = zmq.Context()
            self._exit_stack.push(self._context)

            self._ctl_url = "inproc://ctl"
            self._publisher_ctl = self._context.socket(zmq.PUB)  # pylint: disable=no-member
            self._exit_stack.push(self._publisher_ctl)
            self._publisher_ctl.bind(self._ctl_url)

            self._subscriber_ctl = self._context.socket(zmq.SUB)  # pylint: disable=no-member
            self._exit_stack.push(self._subscriber_ctl)

            # thread
            self._thread = threading.Thread(target=self._listen)
            self._thread.start()
            self.operational = True

        except Exception as err:  # pylint: disable=broad-except
            init_err = err

        if init_err is not None:
            self._exit_stack.close()
            raise init_err  # pylint: disable=raising-bad-type

    def _listen(self) -> None:
        """
        listens on the zeromq subscriber. This function is expected to run in a separate thread.

        :return:
        """
        with self._context.socket(zmq.SUB) as subscriber_ctl:  # pylint: disable=no-member
            subscriber_ctl.connect(self._ctl_url)
            subscriber_ctl.setsockopt_string(zmq.SUBSCRIBE, "")  # pylint: disable=no-member

            poller = zmq.Poller()
            poller.register(subscriber_ctl, zmq.POLLIN)  # pylint: disable=no-member
            poller.register(self._subscriber, zmq.POLLIN)  # pylint: disable=no-member

            while True:
                try:
                    socks = dict(poller.poll())

                    if subscriber_ctl in socks and socks[subscriber_ctl] == zmq.POLLIN:
                        # received an exit signal
                        _ = subscriber_ctl.recv()
                        break

                    if self._subscriber in socks and socks[self._subscriber] == zmq.POLLIN:
                        msg = self._subscriber.recv()
                        self.callback(msg)
                except Exception as err:  # pylint: disable=broad-except
                    self.on_expection(err)
                    break

    def shutdown(self) -> None:
        """
        shuts down the threaded subscriber.

        :return:
        """
        if self.operational:
            self._publisher_ctl.send(data=b'')  # send a shutdown signal to the subscriber_ctl
            self._thread.join()
            self._exit_stack.close()

        self.operational = False

    def __enter__(self) -> 'ThreadedSubscriber':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.operational:
            self.shutdown()


class PersistentStorage:
    """
    persists received messages on disk.
    """

    def __init__(self, persistent_dir: Union[str, pathlib.Path]) -> None:
        if isinstance(persistent_dir, str):
            self.__persistent_dir = pathlib.Path(persistent_dir)
        elif isinstance(persistent_dir, pathlib.Path):
            self.__persistent_dir = persistent_dir
        else:
            raise TypeError("Unexpected type of argument 'persistent_dir': {}".format(type(persistent_dir)))

        self.__persistent_dir.mkdir(exist_ok=True, parents=True)

        self.__mu = threading.Lock()

        self.__first = None  # type: Optional[bytes]
        self.__paths = []  # type: List[pathlib.Path]
        self.__count = 0  # To count messages and name them, so that naming conflicts can be avoided.

        files = sorted(list(self.__persistent_dir.iterdir()))
        for path in files:
            if path.suffix == ".bin":
                self.__paths.append(path)
            elif path.suffix == ".tmp":
                path.unlink()

        if self.__paths:
            stem = self.__paths[-1].stem
            value_err = None  # type: Optional[ValueError]
            try:
                self.__count = int(stem) + 1
            except ValueError as err:
                value_err = err

            if value_err is not None:
                raise ValueError("Failed to reinitialize from the file {!r}. Please make sure nobody else writes files "
                                 "to the persistent directory.".format(self.__paths[-1]))

            pth = self.__paths[0]
            self.__first = pth.read_bytes()

    def front(self) -> Optional[bytes]:
        """
        makes a copy of the first pending message, but does not remove it from the persistent storage's
        internal queue.

        :return: copy of the first message, or None if no message in the queue
        """
        with self.__mu:  # pylint: disable=not-context-manager
            if self.__first is None:
                return None

            msg = copy.deepcopy(self.__first)
            return msg

    def pop_front(self) -> bool:
        """
        removes a message from the persistent storage's internal queue.

        :return: True if there was a message in the queue
        """
        with self.__mu:  # pylint: disable=not-context-manager
            if self.__first is None:
                return False

            pth = self.__paths.pop(0)
            pth.unlink()

            if not self.__paths:
                self.__first = None
            else:
                pth = self.__paths[0]
                self.__first = pth.read_bytes()
            return True

    def add_message(self, msg: Optional[bytes]) -> None:
        """
        adds a message to the persistent storage's internal queue.

        :param msg: message to be added
        """
        if msg is None:
            return

        with self.__mu:  # pylint: disable=not-context-manager

            # Make sure the files can be sorted as strings (which breaks if you have files=[3.bin, 21.bin])
            pth = self.__persistent_dir / "{:030d}.bin".format(self.__count)
            tmp_pth = pth.parent / (pth.name + ".tmp")  # type: Optional[pathlib.Path]

            try:
                assert tmp_pth is not None, "Unexpected tmp_pth None; expected it to be initialized just before."
                tmp_pth.write_bytes(msg)
                tmp_pth.rename(pth)
                tmp_pth = None

                self.__paths.append(pth)
                self.__count += 1

                if self.__first is None:
                    self.__first = msg

            finally:
                if tmp_pth is not None and tmp_pth.exists():
                    tmp_pth.unlink()


class PersistentLatestStorage:
    """
    persists only the latest received message.
    """

    def __init__(self, persistent_dir: Union[str, pathlib.Path]) -> None:
        if isinstance(persistent_dir, str):
            self.__persistent_dir = pathlib.Path(persistent_dir)
        elif isinstance(persistent_dir, pathlib.Path):
            self.__persistent_dir = persistent_dir
        else:
            raise TypeError("unexpected type of argument persistent_dir: {}".format(persistent_dir.__class__.__name__))

        self.__persistent_dir.mkdir(exist_ok=True, parents=True)

        self.__mu = threading.Lock()

        self.__message = None  # type: Optional[bytes]
        self.__persistent_file = self.__persistent_dir / "persistent_message.bin"
        self.new_message = False

        if self.__persistent_file.exists():
            self.__message = self.__persistent_file.read_bytes()
            self.new_message = True

    def add_message(self, msg: Optional[bytes]) -> None:
        """
        replaces the latest message in the internal storage.

        :param msg: new message
        """
        if msg is None:
            return

        with self.__mu:
            tmp_pth = self.__persistent_file.with_suffix(".tmp")
            try:
                tmp_pth.write_bytes(msg)
                tmp_pth.rename(self.__persistent_file)

                self.new_message = True
                self.__message = msg
            finally:
                if tmp_pth.exists():
                    tmp_pth.unlink()

    def message(self) -> Optional[bytes]:
        """
        gets the latest message. Use PersistentLatestStorage.newmessage to check if a new one has arrived.

        :return: latest message or None, if no message so far.
        """
        with self.__mu:
            self.new_message = False
            return copy.deepcopy(self.__message)
