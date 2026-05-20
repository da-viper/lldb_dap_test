import os

def append_to_process_working_directory(test, *paths):
    return os.path.join(test.getBuildDir(), *paths)
