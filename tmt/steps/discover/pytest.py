import copy
from io import StringIO
import os
import sys
from typing import Dict
from contextlib import contextmanager

import click
import fmf
import pytest

import tmt
import tmt.steps.discover
from tmt.utils import DiscoverError


class _PytestPlugin:
    def __init__(self, collected: Dict[str, pytest.Item], testfiles=None, testnames=None):
        self.collected = collected
        self.testnames = None if not testnames else set(testnames)
        self.testfiles = None if not testfiles else set(testfiles)

    def pytest_itemcollected(self, item: pytest.Item):
        # Filter by test file name
        if self.testfiles:
            filename = os.path.basename(item.fspath)
            if filename not in self.testfiles:
                return
        # Filter by test name
        if self.testnames:
            if item.name not in self.testnames:
                return
        self.collected.setdefault(item.fspath, []).append(item)


@contextmanager
def swallow_stdout(where=None):
    saved = sys.stdout
    sys.stdout = where or StringIO()
    try:
        yield
    finally:
        sys.stdout = saved


class DiscoverPytest(tmt.steps.discover.DiscoverPlugin):
    """
    Yadda yadda
    """
    _methods = [tmt.steps.Method(name='pytest', doc=__doc__, order=60)]

    @classmethod
    def options(cls, how=None):
        """ Prepare command line options for given method """
        return [
            click.option(
                '-p', '--path', metavar='ROOT',
                help='collect only tests from the given path.'),
            click.option(
                '-t', '--test', metavar='NAMES', multiple=True,
                help='collect tests by name. If the given name is part of the function, the test will be considered.'),
            click.option(
                '-T', '--testfile', metavar='FILENAME', multiple=True,
                help='collect tests from files with the given filename.'),
            click.option(
                '-F', '--filter', metavar='FILTERS', multiple=True,
                help='collect only tests matching the filter.'),
            click.option(
                '-m', '--marker', metavar='MARKEXPR',
                help='collect only tests matching given mark expression. example: -m \'mark1 and not mark2\'.'),
            click.option(
                '-i', '--ignore', metavar='PATHS', multiple=True,
                help='ignore tests from those folders.'),
            # click.option(
            #     '--pdb', help='start the interactive Python debugger on errors or KeyboardInterrupt.'),
            # click.option(
            #     '--pdbcls', metavar='modulename:classname',
            #     help=('start a custom interactive Python debugger on errors. For example: '
            #           '--pdbcls=IPython.terminal.debugger:TerminalPd')),
        ] + super().options(how=how)

    def go(self):
        """ Discover available tests """
        super().go()
        root_dir = os.path.join(
            self.step.plan.run.tree.root, self.data.get('path', os.curdir))
        options = []
        # Build additional options for pylint
        # if 'pdb' in self.data:
        #     options.append('--pdb')
        # if self.data.get('pdbcls', None):
        #     options.append('--pdbcls={}'.format(self.data.get('pdbcls')))
        if self.data.get('marker'):
            options.append(f"--marker='{self.data.get('marker')}'")
        options.extend([f"--ignore={os.path.join(self.step.plan.run.tree.root, path)}"
                        for path in self.data.get('ignore', [])])
        # Perform pytest collection
        collected = {}
        pytest_plugin = _PytestPlugin(collected=collected,
                                      testnames=self.data.get('test', None),
                                      testfiles=self.data.get('testfile', None))
        with swallow_stdout():
            ret = pytest.main(['--collect-only', '-qqqq'] + options + [root_dir],
                              plugins=(pytest_plugin,))
        if ret not in (0, 5):
            raise DiscoverError(
                f'pytest execution failed with {ret} CWD: {os.path.abspath(os.curdir)}')

        tests = fmf.Tree(dict(summary='tests'))
        names = []
        for testfile in collected:
            for testfunc in collected[testfile]:
                names.append(testfunc.name)
                data = copy.deepcopy(self.data)
                if not 'duration' in data:
                    data['duration'] = tmt.base.DEFAULT_TEST_DURATION_L2
                data['path'] = f"/tests{os.path.relpath(testfile, root_dir)}"
                data['test'] = f"{os.path.relpath(testfile, root_dir)}::{testfunc.name}"
                data.pop('name', None)
                tests.child(name=testfunc.name, data=data)

        tree = tmt.Tree(tree=tests)
        self._tests = tree.tests()

    def tests(self):
        """ Return all discovered tests """
        return self._tests

    def show(self):
        """ Show discover details """
        super().show(['filter', 'path', 'test',
                      'testfile', 'marker', 'ignore'])

    def wake(self):
        """ Wake up the plugin (override data with command line) """
        if 'tests' not in self.data:
            self.data['tests'] = []
        self._tests = []

        for option in ['filter', 'path', 'test', 'testfile', 'marker', 'ignore']:
            value = self.opt(option)
            if value:
                self.data[option] = value
