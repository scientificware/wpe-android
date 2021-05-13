#!/bin/python

"""
This script takes care of fetching, building and installing all WPE Android dependencies,
including libwpe, WPEBackend-android and WPEWebKit.

The cross-compilation work is done by Cerbero: https://github.com/Igalia/cerbero.git

After cloning Cerbero's source through git in the `build` folder, the process starts with
the following Cerbero command:

`./cerbero-uninstalled -c config/cross-android-<android_abi> -f wpewebkit`

where `<android_abi>` varies depending on the given architecture target.

The logic for this command is in the WPEWebKit packaging recipe in Cerbero's repo:
https://github.com/Igalia/cerbero/blob/18f3346042abfa9455bc270019a3c337fae23018/packages/wpewebkit.package

This command triggers the build for all WPEWebKit dependencies. After that WPEWebKit itself
is built. You can find the recipes for all dependencies and WPEWebKit build in the
`recipes` folder of Cerbero's repo.

Once WPEWebKit and all dependencies are built, the packaging step starts.
The list of assets that are packaged is defined by the `files` variable in the packaging recipe.
The syntax `wpeandroid:libs:stl` means 'from the recipe wpeandroid, include the libraries
(`files_libs` in the recipe) and the STL lib (`files_stl` in the recipe).
You can think of the `:` separating the file types as commas in a list. For most recipes
we only care about the libraries, except for WPEWebKit from which we want everything.

The packaging step results in two different tar files. One containing the runtime assets
and another one with the development assets. The content of these tar files is extracted
in the `cerbero/sysroot` folder.

After that we are done with Cerbero and back into the bootstrap script.

Before being able to use the generated libraries, we need to work around a limitation of
Android's package manager. The package manager only unpacks libxxx.so named libraries so
any library with versioning (i.e. libxxx.so.1) will be ignored. To fix this we rename all
versioned libraries to the libxxx.so form. For example, a library named libfoo.so.1 will
become libfoo_1.so. Apart from renaming the actual library files, we need to tweak the
SONAME and NEEDED values as well to reflect the name changes. We also need to take care of
the symbolic links to reflect the naming changes.


The final step is to copy the needed headers and processed libraries into its corresponding
location within the `wpe` project. This is done by the `__install_deps` function.

"""

import argparse
import glob
import os
import re
import requests
import shutil
import subprocess
import sys

from pathlib import Path

class Bootstrap:
    def __init__(self, args):
        self.__version = '2.30.4'
        self.__gstreamer_version = '1.19.0.1'
        self.__arch = args.arch
        self.__build = args.build
        self.__debug = args.debug
        self.__root = os.getcwd()
        self.__build_dir = os.path.join(os.getcwd(), 'cerbero')
        # These are the libraries that the glue code link with, and are required during build
        # time. These libraries go into the `imported` folder and cannot go into the `jniFolder`
        # to avoid a duplicated library issue.
        self.__build_libs = [
            'glib-2.0',
            'libgio-2.0.so',
            'libglib-2.0.so',
            'libgobject-2.0.so',
            'libwpe-1.0.so',
            'libWPEWebKit-1.0.so',
            'libWPEWebKit-1.0_3.so',
            'libWPEWebKit-1.0_3.11.7.so'
        ]
        self.__build_includes = [
            ['glib-2.0', 'glib-2.0'],
            ['libsoup-2.4', 'libsoup-2.4'],
            ['wpe-1.0', 'wpe'],
            ['wpe-android', 'wpe-android'],
            ['wpe-webkit-1.0', 'wpe-webkit'],
            ['xkbcommon', 'xkbcommon']
        ]
        self.__soname_replacements = [
            ('libnettle.so.6', 'libnettle_6.so'), # This entry is not retrievable from the packaged libnettle.so
        ]
        self.__base_needed = set(['libWPEWebKit-1.0_3.so'])
        self.__wpewebkit_binary = 'wpewebkit-android-%s-%s.tar.xz' %(self.__arch, self.__version)
        self.__wpewebkit_runtime_binary = 'wpewebkit-android-%s-%s-runtime.tar.xz' %(self.__arch, self.__version)
        self.__gstreamer_binary = 'gstreamer-1.0-android-%s-%s.tar.xz' %(self.__arch, self.__gstreamer_version)
        self.__gstreamer_runtime_binary = 'gstreamer-1.0-android-%s-%s-runtime.tar.xz' %(self.__arch, self.__gstreamer_version)

    def __fetch_gstreamer_binaries(self):
        print('Fetching gstreamer binaries...')
        gstreamer = requests.get('https://c0e792ecb2ce.ngrok.io/gstreamer-1.0-android-arm64-1.19.0.1.tar.xz', allow_redirects=True)
        open(self.__gstreamer_binary, 'wb').write(gstreamer.content)

    def __fetch_binaries(self):
        assert(self.__build == False)
        print('Fetching binaries...')
        if not os.path.isdir(self.__build_dir):
            os.mkdir(self.__build_dir)
        os.chdir(self.__build_dir)
        wpewebkit = requests.get('https://cloud.igalia.com/s/Z2atNFGGm2Yz5Yw/download', allow_redirects=True)
        open(self.__wpewebkit_binary, 'wb').write(wpewebkit.content)
        wpewebkit_runtime = requests.get('https://cloud.igalia.com/s/pQHeFFdY28xBaoB/download', allow_redirects=True)
        open(self.__wpewebkit_runtime_binary, 'wb').write(wpewebkit_runtime.content)

    def __cerbero_command(self, args):
        os.chdir(self.__build_dir)
        command = [
            './cerbero-uninstalled', '-c',
            '%s/config/cross-android-%s' %(self.__build_dir, self.__arch)
        ]
        command += args
        subprocess.call(command)

    def __patch_wk_for_debug_build(self):
        wk_recipe_path = os.path.join(self.__build_dir, 'recipes', 'wpewebkit.recipe')
        with open(wk_recipe_path, 'r') as recipe_file:
            recipe_contents = recipe_file.read()
        recipe_contents = recipe_contents.replace('-DLOG_DISABLED=1', '-DLOG_DISABLED=0')
        recipe_contents = recipe_contents.replace('-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_BUILD_TYPE=Debug')
        recipe_contents = recipe_contents.replace('self.append_env(\'WEBKIT_DEBUG\', \'\')', 'self.append_env(\'WEBKIT_DEBUG\', \'all\')')
        with open(wk_recipe_path, 'w') as recipe_file:
            recipe_file.write(recipe_contents)

        wk_package_path = os.path.join(self.__build_dir, 'packages', 'wpewebkit.package')
        with open(wk_package_path, 'r') as package_file:
            package_contents = package_file.read()
        package_contents = package_contents.replace('strip = True', 'strip = False')
        with open(wk_package_path, 'w') as package_file:
            package_file.write(package_contents)

    def __ensure_cerbero(self):
        origin = 'https://github.com/Igalia/cerbero.git'
        branch = 'wpe-android'

        if os.path.isdir(self.__build_dir) and os.path.isfile(os.path.join(self.__build_dir, 'cerbero-uninstalled')):
            os.chdir(self.__build_dir)
            subprocess.call(['git', 'reset', '--hard', 'origin/' + branch])
            subprocess.call(['git', 'pull', 'origin', branch])
            os.chdir(self.__root)
        else:
            if os.path.isdir(self.__build_dir):
                shutil.rmtree(self.__build_dir)
            subprocess.call(['git', 'clone', '--branch', branch, origin, 'cerbero'])

        self.__cerbero_command(['bootstrap'])

        if self.__debug:
            self.__patch_wk_for_debug_build()

    def __build_deps(self):
        #self.__cerbero_command(['package', '-f', 'wpewebkit'])
        self.__cerbero_command(['package', '-f', 'gstreamer-1.0'])

    def __bundle_gstreamer(self):
        if not self.__build:
            return
        print('Generating GStreamer bundle')
        os.environ['GSTREAMER_ROOT_ANDROID'] = self.__gstreamer_root
        ndk_project_path = os.path.join(self.__root, 'scripts', 'gstreamer')
        os.environ['NDK_PROJECT_PATH'] = ndk_project_path
        ndk_build = os.path.join(self.__build_dir, 'build', 'android-ndk-21', 'ndk-build')
        subprocess.call([ndk_build, 'NDK_APPLICATION_MK=' + os.path.join(ndk_project_path, 'jni', self.__arch + '.mk')])

        sysroot = os.path.join(self.__build_dir, 'sysroot')
        lib_dir = os.path.join(sysroot, 'lib')
        if self.__arch == 'arm64':
            arch = 'arm64-v8a'
        else:
            arch = self.__arch
        shutil.move(os.path.join(ndk_project_path, 'libs', arch, 'libgstreamer_android.so'), lib_dir)

        main = os.path.join(self.__root, 'wpe', 'src', 'main')

        gstreamer_init_code = os.path.join(main, 'java', 'org')
        if os.path.exists(gstreamer_init_code):
            shutil.rmtree(gstreamer_init_code)
        shutil.copytree(os.path.join(self.__build_dir, 'src', 'org'), gstreamer_init_code)

        ssl = os.path.join(main, 'assets', 'ssl')
        if os.path.exists(ssl):
            shutil.rmtree(ssl)
        shutil.copytree(os.path.join(self.__build_dir, 'src', 'main', 'assets', 'ssl'), ssl)

        # We need to override the path of the pkg-config files to point to the generated bundle
        #tmp_pc_files = os.path.join(sysroot, 'tmp')
        #if os.path.exists(tmp_pc_files):
        #    shutil.rmtree(tmp_pc_files)
        #os.makedirs(tmp_pc_files)
        #pc_files = os.path.join(self.__gstreamer_root, self.__arch, 'lib', 'pkgconfig')
        #for pc in Path(pc_files).glob('*pc*'):
        #    shutil.copy(pc, os.path.join(tmp_pc_files, os.path.basename(pc)))
        #include_dir = os.path.join(sysroot, 'include')
        #pkgconfig_dir = os.path.join(lib_dir, 'pkgconfig')
        #if not os.path.isdir(pkgconfig_dir):
        #    os.mkdir(pkgconfig_dir)
        #for pc in Path(tmp_pc_files).glob('*pc'):
        #    with open(pc, 'r') as pc_file:
        #        pc_contents = pc_file.read()
        #        pc_contents = re.sub('prefix=.*', 'prefix=' + include_dir, pc_contents)
        #        pc_contents = re.sub('libdir=.*', 'libdir=' + lib_dir, pc_contents)
        #        pc_contents = re.sub('.* -L${.*', 'Libs: -L${libdir} -lgstreamer_android', pc_contents)
        #        pc_contents = re.sub('Libs:.*', 'Libs: -L${libdir} -lgstreamer_android', pc_contents)
        #        pc_contents = re.sub('Libs.private.*', 'Libs.private: -lgstreamer_android', pc_contents)
        #    with open(pc, 'w') as pc_file:
        #        pc_file.write(pc_contents)
        #    shutil.move(pc, os.path.join(pkgconfig_dir, os.path.basename(pc)))

    def __extract_deps(self):
        os.chdir(self.__build_dir)
        sysroot = os.path.join(self.__build_dir, 'sysroot')
        if os.path.isdir(sysroot):
            shutil.rmtree(sysroot)
        os.mkdir(sysroot)

        print('Extracting dev files')
        devel_file_path = os.path.join(self.__build_dir, self.__wpewebkit_binary)
        subprocess.call(['tar', 'xf', devel_file_path, '-C', sysroot, 'include', 'lib/glib-2.0'])

        print('Extracting runtime')
        runtime_file_path = os.path.join(self.__build_dir, self.__wpewebkit_runtime_binary)
        subprocess.call(['tar', 'xf', runtime_file_path, '-C', sysroot, 'lib'])

        print('Extracting gstreamer')
        self.__gstreamer_root = os.path.join(sysroot, 'gstreamer-1.0')
        gstreamer_out_path = os.path.join(self.__gstreamer_root, self.__arch)
        os.makedirs(gstreamer_out_path)
        subprocess.call(['tar', 'xf', os.path.join(self.__build_dir, self.__gstreamer_binary), '-C', gstreamer_out_path])

        print('Extracting gstreamer runtime')
        self.__gstreamer_root = os.path.join(sysroot, 'gstreamer-1.0')
        subprocess.call(['tar', 'xf', os.path.join(self.__build_dir, self.__gstreamer_runtime_binary), '-C', gstreamer_out_path])

    def __copy_headers(self, sysroot_dir, include_dir):
        if os.path.exists(include_dir):
            shutil.rmtree(include_dir)
        os.makedirs(include_dir)

        for header in self.__build_includes:
            shutil.copytree(os.path.join(sysroot_dir, 'include', header[0]),
                            os.path.join(include_dir, header[1]))

    def __adjust_soname(self, initial):
        if initial.endswith('.so'):
            return initial

        split = initial.split('.')
        assert len(split) > 2
        if split[-2] == 'so':
            return '.'.join(split[:-2]) + '_' + split[-1] + '.so'
        elif split[-3] == 'so':
            return '.'.join(split[:-3]) + '_' + split[-2] + '_' + split[-1] + '.so'

    def __read_elf(self, lib_path):
        soname_list = []
        needed_list = []

        p = subprocess.Popen(["readelf", "-d", lib_path], stdout=subprocess.PIPE)
        (stdout, stderr) = p.communicate()

        for line in stdout.decode().splitlines():
            needed = re.match("^ 0x[0-9a-f]+ \(NEEDED\)\s+Shared library: \[(.+)\]$", line)
            if needed:
                needed_list.append(needed.group(1))
            soname = re.match("^ 0x[0-9a-f]+ \(SONAME\)\s+Library soname: \[(.+)\]$", line)
            if soname:
                soname_list.append(soname.group(1))

        assert len(soname_list) == 1
        return soname_list[0], needed_list

    def __replace_soname_values(self, lib_path):
        with open(lib_path, 'rb') as lib_file:
            contents = lib_file.read()

        for pair in self.__soname_replacements:
            contents = contents.replace(bytes(pair[0], encoding='utf8'), bytes(pair[1], encoding='utf8'))

        with open(lib_path, 'wb') as lib_file:
            lib_file.write(contents)

    def __replace_needed_gst_lib(self, lib_path):
        gst_libs = [
            'libgstadaptivedemux-1.0.so',
            'libgstallocators-1.0.so',
            'libgstapp-1.0.so',
            'libgstaudio-1.0.so',
            'libgstbadaudio-1.0.so',
            'libgstbasecamerabinsrc-1.0.so',
            'libgstbase-1.0.so',
            'libgstcheck-1.0.so',
            'libgstcodecs-1.0.so',
            'libgstcodecparsers-1.0.so',
            'libgstpbutils-1.0.so',
            'libgstplay-1.0.so',
            'libgstreamer-1.0.so',
            'libgstsdp-1.0.so',
            'libgstrtp-1.0.so',
            'libgsttag-1.0.so',
            'libgsturidownloader-1.0.so',
            'libgstvideo-1.0.so',
        ]
        for gst_lib in gst_libs:
            subprocess.call(['patchelf', '--replace-needed', gst_lib, 'libgstreamer_android.so', lib_path])


    def __copy_libs(self, sysroot_lib, lib_dir, install_list = None):
        if install_list is None:
            if os.path.exists(lib_dir):
                shutil.rmtree(lib_dir)
            os.makedirs(lib_dir)

        sysroot_gio_modules = os.path.join(sysroot_lib, 'gio', 'modules')
        libs_paths = list(map(lambda x: str(x), Path(sysroot_lib).glob('*.so')))
        libs_paths += list(map(lambda x: str(x), Path(sysroot_gio_modules).glob('*.so')))

        for lib_path in libs_paths:
            soname, _ = self.__read_elf(lib_path)
            adjusted_soname = self.__adjust_soname(soname)
            if (adjusted_soname != soname):
                self.__soname_replacements.append((soname, adjusted_soname))
            if not install_list or lib_path in install_list:
                shutil.copy(lib_path, os.path.join(lib_dir, adjusted_soname))

        for pair in self.__soname_replacements:
            assert len(pair[0]) == len(pair[1])

        for lib_path in Path(lib_dir).glob('*.so'):
            self.__replace_soname_values(lib_path)
            self.__replace_needed_gst_lib(lib_path)

    def __copy_jni_libs(self, jni_lib_dir, lib_dir, libs_paths = None):
        if libs_paths is None:
            if os.path.exists(jni_lib_dir):
                shutil.rmtree(jni_lib_dir)
            os.makedirs(jni_lib_dir)
            libs_paths = Path(lib_dir).glob('*.so')

        for lib_path in libs_paths:
            if os.path.basename(lib_path) in self.__build_libs:
                continue
            shutil.copy(lib_path, os.path.join(jni_lib_dir, os.path.basename(lib_path)))

    def __resolve_deps(self, lib_dir):
        soname_set = set()
        needed_set = self.__base_needed

        for lib_path in Path(lib_dir).glob('*.so'):
            soname, needed_list = self.__read_elf(lib_path)
            soname_set.update([soname])
            needed_set.update(needed_list)

        print("NEEDED but not provided:")
        needed_diff = needed_set - soname_set
        if len(needed_diff) == 0:
            print("    <none>")
        else:
            for entry in needed_diff:
                print("    ", entry)

        print("Provided but not NEEDED:")
        provided_diff = soname_set - needed_set
        if len(provided_diff) == 0:
            print("    <none>")
        else:
            for entry in provided_diff:
                print("    ", entry)

    def install_deps(self, sysroot, install_list = None):
        wpe = os.path.join(self.__root, 'wpe')

        self.__copy_headers(sysroot, os.path.join(wpe, 'imported', 'include'))

        if self.__arch == 'arm64':
            android_abi = 'arm64-v8a'
        elif self.__arch == 'arm':
            android_abi = 'armeabi-v7a'
        else:
            raise Exception('Architecture not supported')

        sysroot_lib = os.path.join(sysroot, 'lib')
        lib_dir = os.path.join(wpe, 'imported', 'lib', android_abi)
        libs_paths = None
        if install_list is not None:
            libs_paths = []
            for lib in install_list:
                libs_paths.append(os.path.join(sysroot_lib, lib))
        self.__copy_libs(sysroot_lib, lib_dir, libs_paths)
        self.__resolve_deps(lib_dir)

        jnilib_dir = os.path.join(wpe, 'src', 'main', 'jniLibs', android_abi)
        self.__copy_jni_libs(jnilib_dir, lib_dir, libs_paths)

        gio_dir = os.path.join(jnilib_dir, 'gio', 'modules')
        if os.path.exists(gio_dir):
            shutil.rmtree(gio_dir)
        os.makedirs(gio_dir)
        shutil.copy(os.path.join(sysroot_lib, 'gio', 'modules', 'libgiognutls.so'),
                    os.path.join(gio_dir, 'libgiognutls.so'))

        try:
            os.symlink(os.path.join(lib_dir, 'libWPEBackend-android.so'),
                      os.path.join(lib_dir, 'libWPEBackend-default.so'))
            shutil.copytree(os.path.join(sysroot_lib, 'glib-2.0'),
                            os.path.join(lib_dir, 'glib-2.0'))
        except:
            print("Not copying existing files")

    def run(self):
        if self.__build:
            self.__ensure_cerbero()
            self.__build_deps()
        else:
            self.__fetch_binaries()
        self.__extract_deps()
        self.__bundle_gstreamer()
        self.install_deps(os.path.join(self.__build_dir, 'sysroot'))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script sets the dev environment up'
    )

    parser.add_argument('-a', '--arch', metavar='architecture', required=False, default='arm64', choices=['arm64'], help='The target architecture')
    parser.add_argument('-d', '--debug', required=False, action='store_true', help='Build the binaries with debug symbols')
    parser.add_argument('-b', '--build', required=False, action='store_true', help='Build dependencies instead of fetching the prebuilt binaries from the network')

    args = parser.parse_args()

    print(args)

    Bootstrap(args).run()

