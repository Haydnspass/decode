from copy import deepcopy
from types import SimpleNamespace


class RecursiveNamespace(SimpleNamespace):
    def __init__(self, **kwargs):
        """
        Extension of SimpleNamespace to recursive dictionaries.
        Inspired by https://dev.to/taqkarim/extending-simplenamespace-for-nested-dictionaries-58e8
        """

        super().__init__(**kwargs)
        for key, val in kwargs.items():
            if isinstance(val, dict):
                setattr(self, key, RecursiveNamespace(**val))
            elif isinstance(val, (tuple, list)):
                setattr(self, key, list(map(self.map_entry, val)))

    def __getitem__(self, item):
        out = getattr(self, item)
        if isinstance(out, RecursiveNamespace):
            raise TypeError

        return out

    def to_dict(self):
        d = deepcopy(self.__dict__)  # should not be inplace, otherwise shitty

        for k in d:  # nice little recursion
            if isinstance(d[k], RecursiveNamespace):
                d[k] = d[k].to_dict()

        return d

    def keys(self):
        return self.__dict__.keys()

    @staticmethod
    def map_entry(entry):
        if isinstance(entry, dict):
            return RecursiveNamespace(**entry)

        return entry
