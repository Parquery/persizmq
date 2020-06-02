ARCHIVED ON June 2nd, 2020

persizmq
========

persizmq provides persistence to zeromq. Messages are received in background and stored on disk before further
manipulation.

Currently, we only support the zeromq subscriber. Adding support for other classes can be easily done; we simply have
not had need for them so far.

Usage
=====
Subscriber
----------
The persistent subscriber wraps a zeromq subscriber. We split up the persistence subscription in two components:
a threaded subscriber that listens on the messages in background, and a persistence component that stores the messages
on disk.

Threaded Subscriber
~~~~~~~~~~~~~~~~~~~
The threaded subscriber is implemented as ``persizmq.ThreadedSubscriber``. You need to specify a callback which is
called upon each received message.

You also need to specify on-exception callback in order to handle exceptions raised in the listening thread.

Example:

.. code-block:: python

    import time

    import zmq

    import persizmq

    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
    subscriber.connect("ipc:///some-queue.zeromq")

    def callback(msg: bytes)->None:
        print("received a message: {}".format(msg))

    def on_exception(exception: Exception)->None:
        print("an exception was raised in the listening thread: {}".format(exception))

    with persizmq.ThreadedSubscriber(callback=callback, subscriber=subscriber, on_exception=on_exception):
        # do something while we are listening on messages...
        time.sleep(10)



Storage
~~~~~~~
We provide two storage modes for the received messages:

1. ``persizmq.PersistentStorage``: stores messages in a FIFO queue on disk.
2. ``persizmq.PersistentLatestStorage``: solely stores the newest message on disk.

The storage component is passed directly to the threaded subscriber as a callback.

Example:

.. code-block:: python

    import pathlib

    import zmq

    import persizmq

    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
    subscriber.connect("ipc:///some-queue.zeromq")

    persistent_dir = pathlib.Path("/some/dir")
    storage = persizmq.PersistentStorage(persistent_dir=persistent_dir)

    def on_exception(exception: Exception)->None:
        print("an exception was raised in the listening thread: {}".format(exception))

    with persizmq.ThreadedSubscriber(callback=storage.add_message, subscriber=subscriber, on_exception=on_exception):
        msg = storage.front()  # non-blocking
        if msg is not None:
            print("Received a persistent message: {}".format(msg))
            storage.pop_front()

Filtering
~~~~~~~~~
We also provide filtering components which can be chained on the threaded subscriber. The filtering chains are
particularly handy if you want to persist only a small amount of messages and ignore the rest.

The filters are implemented in ``persizmq.filter`` module.

Example:

.. code-block:: python

    import pathlib

    import zmq

    import persizmq
    import persizmq.filter

    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
    subscriber.connect("ipc:///some-queue.zeromq")

    persistent_dir = pathlib.Path("/some/dir")
    storage = persizmq.PersistentStorage(persistent_dir=persistent_dir)

    def on_exception(exception: Exception)->None:
        print("an exception was raised in the listening thread: {}".format(exception))

    with persizmq.ThreadedSubscriber(
        lambda msg: storage.add_message(persizmq.filter.MaxSize(max_size=1000)(msg)),
        subscriber=subscriber,
        on_exception=on_exception):

        msg = storage.front()  # non-blocking
        if msg is not None:
            print("Received a persistent message: {}".format(msg))
            storage.pop_front()


Installation
============

* Create a virtual environment:

.. code-block:: bash

    python3 -m venv venv3

* Activate it:

.. code-block:: bash

    source venv3/bin/activate

* Install persizmq with pip:

.. code-block:: bash

    pip3 install persizmq

Development
===========

* Check out the repository.

* In the repository root, create the virtual environment:

.. code-block:: bash

    python3 -m venv venv3

* Activate the virtual environment:

.. code-block:: bash

    source venv3/bin/activate

* Install the development dependencies:

.. code-block:: bash

    pip3 install -e .[dev]

* We use tox for testing and packaging the distribution. Assuming that the virtual environment has been activated and
  the development dependencies have been installed, run:

.. code-block:: bash

    tox

* We also provide a set of pre-commit checks that lint and check code for formatting. Run them locally from an activated
  virtual environment with development dependencies:

.. code-block:: bash

    ./precommit.py

* The pre-commit script can also automatically format the code:

.. code-block:: bash

    ./precommit.py  --overwrite

Versioning
==========
We follow `Semantic Versioning <http://semver.org/spec/v1.0.0.html>`_. The version X.Y.Z indicates:

* X is the major version (backward-incompatible),
* Y is the minor version (backward-compatible), and
* Z is the patch version (backward-compatible bug fix).
