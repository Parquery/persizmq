""" provides filters for messages. """

import datetime
import pathlib
import pickle
from typing import Optional, Union


class MaxSize:
    """
    passes only messages whose size does not exceed a pre-defined limit.
    """

    def __init__(self, max_size: int) -> None:
        """
        :param max_size:
                Maximum size of the message to
        """
        self.max_size = max_size

    def __call__(self, msg: Optional[bytes]) -> Optional[bytes]:
        if msg is None:
            return None

        if self.max_size < len(msg):
            return None
        return msg


class MinPeriod:
    """
    passes only the messages which arrive at the minimum period.
    """

    def __init__(self, min_period: float, persistent_dir: Union[None, str, pathlib.Path] = None) -> None:
        """
        :param min_period: The minimum period between two messages.
        :param persistent_dir:
                If not None, the most recent timestamp is stored here and retrieved again upon restart to achieve
                persistence.
        """

        self.min_period = min_period

        if persistent_dir is None:
            self.__persistent_file = None
        elif isinstance(persistent_dir, str):
            self.__persistent_file = pathlib.Path(persistent_dir) / "last_timestamp.pkl"
            pathlib.Path(persistent_dir).mkdir(exist_ok=True, parents=True)
        elif isinstance(persistent_dir, pathlib.Path):
            self.__persistent_file = persistent_dir / "last_timestamp.pkl"
            persistent_dir.mkdir(exist_ok=True, parents=True)
        else:
            raise TypeError("unexpected type of argument persistent_dir: {}".format(persistent_dir.__class__.__name__))

        if self.__persistent_file is not None and self.__persistent_file.exists():
            with self.__persistent_file.open("rb") as fid:
                self.__last_timestamp = pickle.load(fid)

            if not isinstance(self.__last_timestamp, datetime.datetime):
                raise TypeError("the last_timestamp loaded from {!r} is not a datetime.datetime object: {}".format(
                    self.__persistent_file.as_posix(), self.__last_timestamp.__class__.__name__))
        else:
            self.__last_timestamp = None

    def __call__(self, msg: Optional[bytes]) -> Optional[bytes]:  # pylint: disable=unused-argument
        """
        checks if the new message arrived at least min_period seconds after the previous message.

        :param msg: Message to be passed to next filter.
        :return: msg, if the time since the last message is larger than min_period, None otherwise.
        """
        if msg is None:
            return None

        now = datetime.datetime.utcnow()
        if self.__last_timestamp is not None:
            delta_t = (now - self.__last_timestamp).total_seconds()
            if delta_t < self.min_period:
                return None

        self.__last_timestamp = now
        if self.__persistent_file is not None:
            with self.__persistent_file.open("wb") as fid:
                pickle.dump(self.__last_timestamp, fid)

        return msg
