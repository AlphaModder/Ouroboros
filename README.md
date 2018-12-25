## DISCLAIMER: This software is highly experimental. It hasn't been thouroughly tested, and relies on python internals, so there are potentially very strange bugs lurking in it. 

## What Ouroboros is
Ouroboros is an experimental python library that allows one to import python modules into a namespace completely separate from the rest of an application, while still being able to call into their code with no IPC or other intermediary. An arbitrary number of such namespaces can be created, and further code imported by namespaced modules will remain in the namespace.

## What Ouroboros is not
**Ouroboros is not a sandbox, or any kind of security mechanism.** The namespacing it provides is purely for the purpose of importing python scripts without worrying about name conflicts or polluting `sys.path`. Modules are not isolated from the system in any other way. Furthermore, though efforts have been made to ensure that no imported module will accidentally touch the main module namespace, a module that is aware of Ouroboros can easily bypass this. **If you want a sandbox, use PyPy.**

## How it works
Python's import mechanism is implemented in two places. There is `importlib`, a pure Python implementation in the standard library, as well as a version that is partially written in C for performance reasons baked into CPython itself. Normally, both implementations store their state in the globals `sys.meta_path`, `sys.path`, `sys.modules`, `sys.path_importer_cache`, and `sys.path_hooks`. 

An Ouroboros namespace works by loading a fresh instance of `importlib` and redirecting any accesses to those globals to an object associated with that namespace. That way, the existing import system's code can be reused while preserving the separation between different namespaces. Because all copies of `importlib` and the modules they load exist in the same Python environment, there are no limitations on their ability to interact. 

Ouroboros namespaces also alter the `__builtins__` table of any moduled loaded within them, replacing the function `__import__`, which defaults to the CPython implementation mentioned above, with a version that calls into the namespace's modified `importlib`. That way, any import statements made by loaded modules will look in the proper location and not affect the global namespace.

Likewise, the modules `sys`, `importlib`, and `builtins` are all replaced by versions whose import-related functionality is limited to the current namespace. This is for compatibility with modules that use those libraries, and should *not* be used as a security boundary. 

## How it really works
Interestingly, loading a fresh copy of `importlib` and modifying it is not as easy as it seems. Though it seems simple enough to load a copy of it and alter the copy's reference to `sys` by assigning to `importlib.sys`, this does not in fact work. 

Though `importlib` is written in pure Python, the version of importlib loaded by default actually comes from 'frozen' code, Python bytecode that has been precompiled and included in the CPython runtime. One side effect of being housed in the interpreter itself is that frozen code always has access to the 'real' version of `sys`, no matter what. 

One of the main challenges in writing Ouroboros was loading a copy of `importlib` from source, rather than frozen code, and ensuring that no references to frozen code remain in it after it has been loaded. This process is complicated by the fact that `importlib` is actually divided into smaller modules, and that each of them attempts to access the frozen version of the others explicitly. 

In the end, the solution was to instruct the frozen `importlib` to load each of its submodules from source<sup>1</sup>, and then to manually replace the submodules' references to frozen code with references to each other. Of course, the tricky part is tracking down all the references to frozen code in the first place.

<sup>1</sup>The idea of using the frozen `importlib` to load itself in pieces and to then link them to eachother is where the name Ouroboros comes from. 

## Performance & Limitations
I have not yet tested the performance of Ouroboros' import mechanism against the existing C or Python implementations, though I would expect it to perform slightly slower than C for obvious reasons. If there is any overhead, it should only be when importing modules, not when using them, and imports are not typically a bottleneck anyway.

Currently the only known limitation is that it's impossible to block built-in modules from registering themselves to `sys.modules` when imported for the first time, since this happens in C (`_imp_create_builtin`), so we have to manually remove them in that case.