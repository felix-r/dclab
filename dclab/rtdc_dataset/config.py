"""RT-DC dataset configuration"""
import copy
from collections import UserDict
import json
import numbers
import pathlib
import sys
import warnings

import numpy as np

from .. import definitions as dfn


class WrongConfigurationTypeWarning(UserWarning):
    pass


class EmptyConfigurationKeyWarning(UserWarning):
    pass


class UnknownConfigurationKeyWarning(UserWarning):
    pass


class BadUserConfigurationKeyWarning(UserWarning):
    pass


class BadUserConfigurationValueWarning(UserWarning):
    pass


class ConfigurationDict(UserDict):
    def __init__(self, section=None, *args, **kwargs):
        """A case-insensitive dict that is section-aware

        Instantiate this dictionary like any other dictionary.
        All keys will be treated as lower-case keys. If `section`
        is given, new entries will be checked using the function
        :func:`verify_section_key`.
        """
        self.section = section
        super(ConfigurationDict, self).__init__(*args, **kwargs)
        self._convert_keys()

    def __getitem__(self, key):
        return super(ConfigurationDict,
                     self).__getitem__(self.__class__._k(key))

    def __setitem__(self, key, value):
        key = self.__class__._k(key)
        # make sure "section: key" exists
        if self.section:
            valid = verify_section_key(self.section, key)
            # check for empty string values
            if valid and isinstance(value, str) and len(value) == 0:
                warnings.warn(
                    "Empty value for [{}]: '{}'!".format(self.section, key),
                    EmptyConfigurationKeyWarning,
                )
                valid = False
        else:
            valid = True
        if value is None:
            warnings.warn(
                f"Bad value '{value}' for [{self.section}]: '{key}'!",
                BadUserConfigurationValueWarning,
            )
            valid = False
        if valid:
            # only set valid keys
            if self.section:
                typ = dfn.get_config_value_type(self.section, key)
                if typ is not None and not isinstance(value, typ):
                    warnings.warn(
                        f"Type of confguration key [{self.section}]: {key} "
                        f"should be {typ}, got {type(value)}!",
                        WrongConfigurationTypeWarning)
                # convert value to its correct type (independent of case above)
                convfunc = dfn.get_config_value_func(self.section, key)
                value = convfunc(value)

            super(ConfigurationDict, self).__setitem__(key, value)

    def __delitem__(self, key):
        return super(ConfigurationDict,
                     self).__delitem__(self.__class__._k(key))

    def __contains__(self, key):
        return super(ConfigurationDict,
                     self).__contains__(self.__class__._k(key))

    @classmethod
    def _k(cls, key):
        """Convert a key to lower case"""
        return key.lower() if isinstance(key, str) else key

    def _convert_keys(self):
        for k in list(self.keys()):
            v = super(ConfigurationDict, self).pop(k)
            self.__setitem__(k, v)

    def get(self, key, *args, **kwargs):
        return super(ConfigurationDict,
                     self).get(self.__class__._k(key), *args, **kwargs)

    def items(self):
        keys = list(self.keys())
        keys.sort()
        out = [(k, self[k]) for k in keys]
        return out

    def pop(self, key, *args, **kwargs):
        return super(ConfigurationDict,
                     self).pop(self.__class__._k(key), *args, **kwargs)

    def setdefault(self, key, *args, **kwargs):
        return super(ConfigurationDict,
                     self).setdefault(self.__class__._k(key), *args, **kwargs)

    def update(self, E=None, **F):
        if E is None:
            E = {}
        for key in E:
            self.__setitem__(key, E[key])
        for key in F:
            self.__setitem__(key, F[key])


class Configuration(object):
    def __init__(self, files=None, cfg=None, disable_checks=False):
        """Configuration class for RT-DC datasets

        This class has a dictionary-like interface to access
        and set configuration values, e.g.

        .. code::

            cfg = load_from_file("/path/to/config.txt")
            # access the channel width
            cfg["setup"]["channel width"]
            # modify the channel width
            cfg["setup"]["channel width"] = 30

        Parameters
        ----------
        files: list of files
            The config files with which to initialize the configuration
        cfg: dict-like
            The dictionary with which to initialize the configuration
        disable_checks: bool
            Set this to True if you want to avoid checking against
            section and key names defined in `dclab.definitions`
            using :func:`verify_section_key`. This avoids excess
            warning messages when loading data from configuration
            files not generated by dclab.
        """
        if cfg is None:
            cfg = {}
        if files is None:
            files = []
        self.disable_checks = disable_checks

        self._cfg = ConfigurationDict()

        # set initial default values
        self._init_default_filter_values()

        # Update with additional dictionary
        self.update(cfg)

        # Load configuration files
        for f in files:
            self.update(load_from_file(f))

    def __contains__(self, key):
        return self._cfg.__contains__(key)

    def __getitem__(self, sec):
        if sec not in self and (sec in dfn.config_keys or sec == "user"):
            # create an empty section for user-convenience
            section = None if self.disable_checks else sec
            self._cfg[sec] = ConfigurationDict(section=section)
        item = self._cfg.__getitem__(sec)
        return item

    def __iter__(self):
        return self._cfg.__iter__()

    def __len__(self):
        return len(self._cfg)

    def __repr__(self):
        rep = ""
        keys = sorted(list(self.keys()))
        for key in keys:
            rep += "- {}\n".format(key)
            subkeys = sorted(list(self[key].keys()))
            for subkey in subkeys:
                rep += "   {}: {}\n".format(subkey, self[key][subkey])
        return rep

    def __setitem__(self, *args):
        self._cfg.__setitem__(*args)

    def _init_default_filter_values(self):
        """Set default initial values

        The default values are hard-coded for backwards compatibility
        and for several functionalities in dclab.
        """
        # Do not filter out invalid event values
        self["filtering"]["remove invalid events"] = False
        # Enable filters switch is mandatory
        self["filtering"]["enable filters"] = True
        # Limit events integer to downsample output data
        self["filtering"]["limit events"] = 0
        # Polygon filter list
        self["filtering"]["polygon filters"] = []
        # Defaults to no hierarchy parent
        self["filtering"]["hierarchy parent"] = "none"

        # Make sure that all filtering values have a default value
        # (otherwise we will get problems with resetting filters)
        for item in dfn.CFG_ANALYSIS["filtering"]:
            if item[0] not in self["filtering"]:
                raise KeyError(
                    "No default value set for [filtering]:{}".format(item[0]))

    def copy(self):
        """Return copy of current configuration"""
        return Configuration(cfg=copy.deepcopy(self._cfg))

    def get(self, key, other):
        """Famous `dict.get` function

        .. versionadded:: 0.29.1

        """
        if key in self:
            return self[key]
        else:
            return other

    def tojson(self):
        """Convert the configuration to a JSON string

        Note that the data type of some configuration options
        will likely be lost.
        """
        # Dear future person,
        # if you would like to implement `fromjson`, you will have
        # to set the `section` properly in the ConfigurationDict.
        # Besides the data types, there might be other things to
        # look out for. ~paulmueller
        return json.dumps(dict(self),
                          cls=ConfigurationJSONEncode,
                          sort_keys=True)

    def keys(self):
        """Return the configuration keys (sections)"""
        return self._cfg.keys()

    def save(self, filename):
        """Save the configuration to a file"""
        filename = pathlib.Path(filename)
        out_str = self.tostring()
        with filename.open("w") as f:
            f.write(out_str)

    def tostring(self, sections=None):
        """Convert the configuration to its string representation

        The optional argument `sections` allows to export only
        specific sections of the configuration, i.e.
        `sections=dclab.dfn.CFG_METADATA` will only export
        configuration data from the original measurement and no
        filtering data.
        """
        out = []
        if sections is None:
            keys = sorted(list(self.keys()))
        else:
            keys = sorted([k for k in sections if k in self.keys()])
        for key in keys:
            out.append("[{}]".format(key))
            section = self[key]
            ikeys = list(section.keys())
            ikeys.sort()
            for ikey in ikeys:
                var, val = keyval_typ2str(ikey, section[ikey])
                out.append("{} = {}".format(var, val))
            out.append("")

        out_str = ""
        for i in range(len(out)):
            # win-like line endings
            out_str += out[i]+"\n"
        return out_str

    def update(self, newcfg):
        """Update current config with a dictionary"""
        for sec in newcfg.keys():
            if sec not in self._cfg:
                section = None if self.disable_checks else sec
                self._cfg[sec] = ConfigurationDict(section=section)
            self._cfg[sec].update(newcfg[sec])


class CaseInsensitiveDict(ConfigurationDict):
    def __init__(self, *args, **kwargs):
        warnings.warn("CaseInsensitiveDict is deprecated, use "
                      + "ConfigurationDict instead.",
                      DeprecationWarning)
        super(CaseInsensitiveDict, self).__init__(*args, **kwargs)


class ConfigurationJSONEncode(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ConfigurationDict):
            return dict(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, numbers.Integral):
            return int(obj)
        elif isinstance(obj, numbers.Number):
            return float(obj)
        elif isinstance(obj, (bool, np.bool_)):
            return bool(obj)
        return json.JSONEncoder.default(self, obj)


def verify_section_key(section, key):
    """Return True if the section-key combination exists"""
    wcount = 0
    if dfn.config_key_exists(section, key):
        pass
    elif section in ["plotting", "analysis"]:
        # hijacked by Shape-Out 1
        warnings.warn("The '{}' configuration key is deprecated!".format(
            section), UnknownConfigurationKeyWarning)
        wcount += 1
    elif section == "filtering":
        if key.endswith(" min") or key.endswith(" max"):
            feat = key[:-4]
            if not dfn.scalar_feature_exists(feat):
                warnings.warn(
                    "A range has been specified for an unknown feature "
                    + "'{}' in the 'filtering' section!".format(feat),
                    UnknownConfigurationKeyWarning)
                wcount += 1
        elif key == "limit events auto":
            # Shape-Out 1 used this to limit the number of events to
            # a common minimum.
            if sys.version_info[0] != 2:
                warnings.warn("The 'limit events auto' configuration key "
                              " in the 'filtering' section is deprecated!")
                wcount += 1
        else:
            warnings.warn(
                "Unknown key '{}' in the 'filtering' section!".format(key),
                UnknownConfigurationKeyWarning)
            wcount += 1
    elif section == "user":
        # the keys must be strings for clarity
        if not isinstance(key, str):
            warnings.warn("The 'user' section keys must be strings, "
                          f"got '{key}' of type '{type(key)}'!",
                          BadUserConfigurationKeyWarning)
            wcount += 1
        elif len(key.strip()) == 0:
            warnings.warn("The 'user' section keys must not be empty strings "
                          "or consist of whitespace characters only!",
                          BadUserConfigurationKeyWarning)
            wcount += 1
    elif section not in dfn.config_keys:
        warnings.warn("Unknown section '{}'!".format(section),
                      UnknownConfigurationKeyWarning)
        wcount += 1
    else:
        warnings.warn(
            "Unknown key '{}' in the '{}' section!".format(key, section),
            UnknownConfigurationKeyWarning)
        wcount += 1

    return wcount == 0


def load_from_file(cfg_file):
    """Load the configuration from a file

    Parameters
    ----------
    cfg_file: str
        Path to configuration file

    Returns
    -------
    cfg : ConfigurationDict
        Dictionary with configuration parameters
    """
    path = pathlib.Path(cfg_file).resolve()
    with path.open("r", errors="replace") as f:
        code = f.readlines()

    cfg = ConfigurationDict()
    for line in code:
        # We deal with comments and empty lines
        # We need to check line length first and then we look for
        # a hash.
        line = line.split("#")[0].strip()
        if len(line) != 0:
            if line.startswith("[") and line.endswith("]"):
                sec = line[1:-1].lower()
                if sec not in cfg:
                    cfg[sec] = ConfigurationDict()
                continue
            elif not line.count("="):
                # ignore invalid lines
                continue
            var, val = line.split("=", 1)
            var = var.strip().lower()
            val = val.strip("' ").strip('" ').strip()
            if len(val) == 0:
                # skip invalid values
                continue
            # convert parameter value to correct type
            if dfn.config_key_exists(sec, var):
                convfunc = dfn.get_config_value_func(sec, var)
                val = convfunc(val)
            else:
                # unknown parameter (e.g. plotting in Shape-Out), guess type
                var, val = keyval_str2typ(var, val)
            if len(var) != 0 and len(str(val)) != 0:
                cfg[sec][var] = val
    return cfg


def keyval_str2typ(var, val):
    """Convert a variable from a string to its correct type

    Parameters
    ----------
    var: str
        The variable name
    val: str
        The value of the variable represented as a string

    Returns
    -------
    varout: str
        Stripped lowercase `var`
    valout: any type
        The value converted from string to its presumed type

    Notes
    -----
    This method is heuristic and is only intended for usage in
    dclab.

    See Also
    --------
    keyval_typ2str: the opposite
    """
    if not (isinstance(val, str)):
        # already a type:
        return var.strip(), val
    var = var.strip().lower()
    val = val.strip()
    # Find values
    if len(var) != 0 and len(val) != 0:
        # check for float
        if val.startswith("[") and val.endswith("]"):
            if len(val.strip("[],")) == 0:
                # empty list
                values = []
            else:
                values = val.strip("[],").split(",")
                values = [float(v) for v in values]
            return var, values
        elif val.lower() in ["true", "y"]:
            return var, True
        elif val.lower() in ["false", "n"]:
            return var, False
        elif val[0] in ["'", '"'] and val[-1] in ["'", '"']:
            return var, val.strip("'").strip('"').strip()
        elif dfn.scalar_feature_exists(val):
            return var, val
        else:
            try:
                return var, float(val.replace(",", "."))
            except ValueError:
                return var, val


def keyval_typ2str(var, val):
    """Convert a variable to a string

    Parameters
    ----------
    var: str
        The variable name
    val: any type
        The value of the variable

    Returns
    -------
    varout: str
        Stripped lowercase `var`
    valout: any type
        The value converted to a useful string representation

    See Also
    --------
    keyval_str2typ: the opposite
    """
    varout = var.strip()
    if isinstance(val, list):
        data = ", ".join([keyval_typ2str(var, it)[1] for it in val])
        valout = "["+data+"]"
    elif isinstance(val, float):
        valout = "{:.12f}".format(val)
    else:
        valout = "{}".format(val)
    return varout, valout
