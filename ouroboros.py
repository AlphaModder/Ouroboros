import importlib, sys, os, builtins, _imp, types

def dup_module(module, fake_sys):
    spec = importlib.util.find_spec(module.__name__)
    spec.loader = importlib.machinery.SourceFileLoader(module.__name__, module.__file__)
    spec.name = module.__name__
    spec.origin = module.__file__

    new_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(new_module)
    fake_sys.__dict__["modules"][module.__name__] = new_module
    return new_module

def patch_loader(loader, builtins, override_modules):
    exec_module = loader.exec_module
    create_module = loader.create_module
    def new_create_module(spec):
        if spec.name in override_modules.keys():
            print("Override hit: {}".format(spec.name))
            return override_modules[spec.name]
        elif create_module:
            remove_after = loader.__name__ == "BuiltinImporter" and not spec.name in sys.modules
            module = create_module(spec)
            if module is not None and remove_after:
                del sys.modules[spec.name] # We can't block builtin modules from registering themselves to sys.modules
            return module
        else:
            return None

    def new_exec_module(module):
        module.__dict__["__builtins__"] = builtins.__dict__
        if not module.__name__ in override_modules:
            exec_module(module)
    loader.create_module = new_create_module
    loader.exec_module = new_exec_module

def patch_finder(finder, builtins, override_modules):
    find_spec = finder.find_spec
    def new_find_spec(fullname, path, target=None):
        spec = find_spec(fullname, path, target)
        if spec:
            patch_loader(spec.loader, builtins, override_modules)
        return spec
    finder.find_spec = new_find_spec
    return finder

class DictWrapper(dict):
    def __init__(self, wrap):
        self.__fake = wrap._WrappedModule__fake
        self.__real = wrap._WrappedModule__real
        self.__fake_attributes = wrap._WrappedModule__fake_attributes
        self.update(self.__real.__dict__)
        self.update({a: getattr(self.__fake, a) for a in self.__fake_attributes})

    def __setitem__(self, name, value):
        if name in self.__fake_attributes:
            setattr(self.__fake, name)
        self.__real.__dict__[name] = value
        super().__setitem__(name, value)

    def __delitem__(self, name):
        if name in self.__fake_attributes:
            delattr(self.__fake, name)
        del self.__real.__dict__[name]
        super().__delitem__(name)

class WrappedModule(types.ModuleType):
    def __init__(self, module, fake, fake_attributes):
        super().__setattr__("_WrappedModule__real", module)
        super().__setattr__("_WrappedModule__fake", fake)
        super().__setattr__("_WrappedModule__fake_attributes", fake_attributes)
        
    def __getattribute__(self, name):
        if name == "__dict__":
            return DictWrapper(self)
        return super().__getattribute__(name)

    def __getattr__(self, name):
        if name in self.__fake_attributes:
            return getattr(self.__fake, name)
        return getattr(self.__real, name)

    def __setattr__(self, name, value):
        if name in self.__fake_attributes:
            return setattr(self.__fake, name, value)
        return setattr(self.__real, name, value)

# Create a copy of importlib completely separated from the current one
def create_new_importlib(path=None, modules=None):
    if path is None:
        path = sys.path.copy()
    if modules is None:
        modules = sys.modules.copy()
    
    fake_sys = types.ModuleType("sys", "A fake version of sys.")
    
    fake_sys.__dict__.update({
        "path": path,
        "modules": modules,
        "path_importer_cache": {},
        "path_hooks": [],
        "builtin_module_names": sys.builtin_module_names,
        "flags": sys.flags,
        "platform": sys.platform,
        "meta_path": sys.meta_path,
        "implementation": sys.implementation,
        "dont_write_bytecode": sys.dont_write_bytecode,
    })
    
    new_bootstrap = dup_module(importlib._bootstrap, fake_sys)
    new_bootstrap._setup(fake_sys, _imp)

    new_bootstrap_external = dup_module(importlib._bootstrap_external, fake_sys)
    new_bootstrap_external._install(new_bootstrap)
    new_bootstrap._bootstrap_external = new_bootstrap_external

    new_importlib = dup_module(importlib, fake_sys)
    new_importlib.sys = fake_sys
    new_importlib._bootstrap = new_bootstrap
    new_importlib._bootstrap_external = new_bootstrap_external
    new_importlib.__import__ = new_importlib._bootstrap.__import__

    wrapped_builtins = WrappedModule(builtins, types.SimpleNamespace(__import__=new_importlib.__import__), ["__import__"])

    module_overrides = {
        "sys" : WrappedModule(sys, new_importlib.sys, ["path", "modules", "path_importer_cache", "path_hooks", "meta_path"]),
        "builtins" : wrapped_builtins,
        "importlib" : new_importlib,
        "_frozen_importlib" : new_importlib,
        "_frozen_importlib_external" : new_importlib._bootstrap_external,
    }
    
    fake_sys.__dict__["meta_path"] = [patch_finder(f, wrapped_builtins, module_overrides) for f in 
        [new_bootstrap.BuiltinImporter, new_bootstrap.FrozenImporter, new_bootstrap_external.PathFinder]
    ]
    
    new_importlib.sys.path_importer_cache.clear()

    return new_importlib

class ImportContainer:
    def __init__(self, path=None, modules=None):
        self.importlib = create_new_importlib(path, modules)
        self.path = self.importlib.sys.path
        self.modules = self.importlib.sys.modules
        self.path_hooks = self.importlib.sys.path_hooks
        self.meta_path = self.importlib.sys.meta_path

    def import_module(self, name, package=None):
        return self.importlib.import_module(name, package)

