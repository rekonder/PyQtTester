#!/usr/bin/env python3

import sys
from collections import namedtuple
from itertools import chain
from importlib import import_module


def parse_args():
    from argparse import ArgumentParser
    argparser = ArgumentParser()
    argparser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print verbose (debug) information.')
    argparser.add_argument(
        '--qt', metavar='QT_VERSION', default='4', choices='45',
        help='The version of PyQt to run the entry-point app with (4 or 5).')
        # TODO: default try to figure out Qt version by grepping entry-point
    group = argparser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--record', metavar='SCENARIO',
        help='Record the events the user sends to the entry-point application '
             'into the scenario file.')
    group.add_argument( # TODO
        '--replay', metavar='SCENARIO',
        help='Replay the scenario.')
    group.add_argument( # TODO
        '--info', metavar='SCENARIO',
        help='Explain in human-readable form events the scenario contains.')
    argparser.add_argument(
        '--main', '-m', metavar='MODULE_PATH',
        help='The application entry point (either a module to invoke as '
             '"__main__", or a path.to.main.function).')
    argparser.add_argument( # TODO
        '--filter-include', metavar='FILTERS',
        help='When recording, record only events that match the filter.')
    argparser.add_argument( # TODO
        '--filter-exclude', metavar='FILTERS',
        help="When recording, don't record events that match the filter.")
    argparser.add_argument( # TODO
        '--fuzzy', action='store_true',
        help='Fuzzy-matching of event target objects.')
    argparser.add_argument( # TODO
        '--x11', action='store_true',
        help='When replaying scenarios, do it in a new, headless X11 server.')
    argparser.add_argument( # TODO
        '--coverage', action='store_true',
        help='Run the coverage analysis simultaneously.')
    args = argparser.parse_args()

    def init_logging(verbose=False):
        import logging
        global log
        log = logging.getLogger()
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        log.addHandler(handler)
        if verbose:
            log.setLevel(logging.DEBUG)

    init_logging(args.verbose)

    def error(*args, **kwargs):
        log.error(*args, **kwargs)
        sys.exit(1)

    if args.record or args.replay:
        if not args.main:
            error('--record/--replay require --main ("module.path.to.main" function)')

        def _run(entry_point=args.main):
            # Make the application believe it was run unpatched
            sys.argv = [entry_point]

            log.debug('Importing module %s ...', entry_point)
            try:
                module = import_module(entry_point)
                # TODO: make the following two lines work
                module.__name__ = '__main__'  # enter __name__ == '__main__'
                log.info('Running %s', entry_point)
            except ImportError as e:
                # Entry point is not a module but a main function
                try:
                    module, entry = entry_point.rsplit('.', 1)
                    log.debug('Failed. Importing module %s', module)
                    module = import_module(module)
                    log.info('Running %s', entry_point)
                    entry = getattr(module, entry)
                except (ValueError, ImportError) as e:
                    error("Can't import '%s': %s", module, e)
                # If entry is not a module but a (main) function, do call it
                if callable(entry):
                    entry()
                else:
                    error('%s is not a function', entry_point)

        args.main = _run
    if args.record:
        try: args.record = open(args.record, 'wb')
        except Exception as e:
            error('--record: %s', e)
    if args.replay:
        try: args.replay = open(args.replay, 'rb')
        except Exception as e:
            error('--replay: %s', e)
    if args.coverage:
        # TODO: https://coverage.readthedocs.org/en/coverage-4.0.2/api.html#api
        #       https://nose.readthedocs.org/en/latest/plugins/cover.html#source
        ...
    return args


# class PathElement(namedtuple):
#     """Element in """
#     def __new__(cls, *args):
#         super().__new__('PathElement', ('index', 'type', 'name'))
#     def __init__(self, index, type, name):
#         self.index = index
#         self.type = type
#         self.name = name
#
#     def __repr__(self):
#         return '(' + ', '.join((self.index, self.type, self.name)) + ')'

PathElement = namedtuple('PathElement', ('index', 'type', 'name'))


class Resolver:
    FUZZY_MATCHING = False

    @staticmethod
    def _qenum_key(base, value, klass=None):
        """Return Qt enum value as string name of its key.

        Modelled after code by Florian "The Compiler" Bruhin:
        https://github.com/The-Compiler/qutebrowser/blob/master/qutebrowser/utils/debug.py#L91-L167

        Parameters
        ----------
        base: type
            The type object the enum is in, e.g. QFrame or QtCore.Qt.
        value: enum value (int)
            The value of the enum, e.g. Qt.LeftButton
        klass: type
            The enum class the value belongs to, or None to auto-guess.

        Returns
        -------
        key: str
            The key associated with the value if found or '' otherwise.

        Example
        -------
        >>> _qenum_key(Qt, Qt.LeftButton)
        'Qt.LeftButton'
        >>> _qenum_key(Qt, Qt.LeftButton | Qt.RightButton)
        ''
        """
        klass = klass or value.__class__

        if klass == int:  # Can't guess enum class of an int
            return ''

        meta_object = getattr(base, 'staticMetaObject', None)
        if meta_object:
            enum = meta_object.indexOfEnumerator(klass.__name__)
            key = meta_object.enumerator(enum).valueToKey(value)
        else:
            try:
                key = next(name for name, obj in base.__dict__.items()
                           if isinstance(obj, klass) and obj == value)
            except StopIteration:
                key = ''
        return (base.__name__ + '.' + key) if key else ''

    @classmethod
    def _qflags_key(cls, base, value, klass=None):
        """Convert a Qt QFlags value to its keys as '|'-separated string.

        Modelled after code by Florian "The Compiler" Bruhin:
        https://github.com/The-Compiler/qutebrowser/blob/master/qutebrowser/utils/debug.py#L91-L167

        Parameters
        ----------
        base: type
            The type object the flags are in, e.g. QtCore.Qt
        value: int
            The flags value to convert to string.
        klass: type
            The flags class the value belongs to, or None to auto-guess.

        Returns
        -------
        keys: str
            The keys associated with the flags as a '|'-separated string
            if they were found; '' otherwise.

        Note
        ----
        Passing a combined value (e.g. Qt.AlignCenter) will get the names
        of the individual bits (Qt.AlignVCenter | Qt.AlignHCenter).

        Bugs
        ----
        https://github.com/The-Compiler/qutebrowser/issues/42
        """
        klass = klass or value.__class__
        if klass == int:
            return ''
        if klass.__name__.endswith('s'):
            klass = getattr(base, klass.__name__[:-1])
        keys = []
        mask = 1
        value = int(value)
        while mask <= value:
            if value & mask:
                keys.append(cls._qenum_key(base, klass(mask), klass=klass))
            mask <<= 1
        if not keys and value == 0:
            keys.append(cls._qenum_key(base, klass(0), klass=klass))
        return '|'.join(filter(None, keys))

    @classmethod
    def _serialize_value(cls, value, attr):
        """Return str representation of value for attribute attr."""
        value_type = type(value)
        if value_type == int:
            if attr == 'key':
                global QT_KEYS
                return QT_KEYS[value]
            return str(value)
        if value_type == str:
            return value
        if value_type == bool:
            return str(value)
        if isinstance(value, (QtCore.QPointF, QtCore.QPoint)):
            return ...
        if isinstance(value, (QtCore.QRectF, QtCore.QRect)):
            return ...
        # Perhaps it's an enum value from Qt namespace
        assert isinstance(Qt.LeftButton, int)
        if isinstance(value, int):
            s = cls._qenum_key(Qt, value)
            if s: return s
        # Finally, if it ends with 's', it's probably a QFlags object
        # combining the flags of associated Qt.<name-without-s> type, e.g.
        # bitwise or-ing Qt.MouseButton values (Qt.LeftButton | Qt.RightButton)
        # makes a Qt.MouseButtons object:
        assert isinstance((Qt.LeftButton | Qt.RightButton), Qt.MouseButtons)
        if value.__class__.__name__.endswith('s'):
            s = cls._qflags_key(Qt, value)
            if s: return s

        raise ValueError

    EVENT_ATTRIBUTES = {
        # Q*Event attributes, ordered as the constructor takes them
        'QMouseEvent':'pos globalPos button buttons modifiers'.split(),
        'QKeyEvent': 'key modifiers text isAutoRepeat count'.split(),
    }

    @classmethod
    def serialize_event(cls, event):
        assert any('QEvent' == cls.__name__
                   for cls in event.__class__.__mro__), (event, event.__class__.__mro__)
        event_type = type(event)
        event_attributes = cls.EVENT_ATTRIBUTES.get(event_type.__name__, ())
        if not event_attributes:
            log.warning('Unknown event: %s, type=%s, mro=%s',
                        event_type, event.type(), event_type.__mro__)

        args = [event_type.__name__]
        args.append(cls._qenum_key(QtCore.QEvent, event.type()))

        for attr in event_attributes:
            value = getattr(event, attr)()
            try: args.append(cls._serialize_value(value, attr))
            except ValueError:
                log.warning("Can't serialize object {} of type {} "
                            "for attribute {}".format(value,
                                                      value.__class__.__mro__,
                                                      attr))
            # PROBLEM
            # TODO: this is a problem. Qt requires that types of arguments to
            # its constructors match strictly, i.e. QMouseEvent doesn't accept
            # 0x2000000 (an int) as modifiers, but accepts Qt.ShiftModifier.
            # This will be the most pain.

            # Possible workarounds:
            # * Qt.MouseButton.__instancecheck__(Qt.LeftButton) -> True
            # * Named enums picklable (http://pyqt.sourceforge.net/Docs/PyQt5/pickle.html)
            #   But not (LeftButton | RightButton, which is QtCore.MouseButtons which doesn't resolve
        log.debug('Serialized event: %s', args)
        return tuple(args)

    @staticmethod
    def deserialize_event(event):
        if event[0] == 'QEvent':
            assert len(event) == 2
            event = QtCore.QEvent(eval('QtCore.' + event[1]))
            return event
        event = eval('QtGui.' + event[0] + '(' + ', '.join(event[1:]) + ')')
        return event

    @classmethod
    def serialize_object(cls, obj):
        assert any('QObject' == cls.__name__
                   for cls in type(obj).mro()), (obj, type(obj).mro())

        def _canonical_path(obj):

            def _index_by_type(lst, obj):
                return [i for i in lst if type(i) == type(obj)].index(obj)

            parent = obj.parent()
            while parent is not None:
                yield obj, _index_by_type(parent.children(), obj)
                obj = parent
                parent = parent.parent()
            yield obj, _index_by_type(QtGui.qApp.topLevelWidgets(), obj)

        # path = '/'.join(reversed(['[{}]{}({})'.format(index_by_type,
        #                                               type(obj).__name__,
        #                                               obj.objectName())
        #                           for obj, index_by_type in _canonical_path(obj)]))
        path = tuple(reversed([PathElement(index_by_type, type(obj), obj.objectName())
                               for obj, index_by_type in _canonical_path(obj)]))
        log.debug('Serialized object path: %s', path)
        return path

    @classmethod
    def deserialize_object(cls, qApp, path):
        target = path[-1]
        # Find target object by name
        if target.name:
            obj = qApp.findChild(target.type, target.name)
            if obj:
                return obj

        # If target doesn't have a name, find the object in the tree
        # FIXME: The logic here may need rework

        def filtertype(target_type, iterable):
            return [i for i in iterable if type(i) == target_type]

        def get_candidates(widget, i):
            if not (type(widget) == path[i].type and
                    (not path[i].name or path[i].name == widget.objectName())):
                return

            if i == len(path) - 1:
                return widget

            # If fuzzy matching, all the children widgets are considered;
            # otherwise just the one in the correct position
            children = widget.children()
            if not cls.FUZZY_MATCHING:
                target = path[i + 1]
                try:
                    children = (filtertype(target.type, children)[target.index],)
                except IndexError:
                    # Insufficient children of correct type
                    return

            for child in children:
                obj = get_candidates(child, i + 1)
                if obj:
                    return obj

        target = path[0]
        widgets = qApp.topLevelWidgets()
        if not cls.FUZZY_MATCHING:
            try:
                widgets = (filtertype(target.type, widgets)[target.index],)
            except IndexError:
                return
        for window in widgets:
            obj = get_candidates(window, 0)
            if obj:
                return obj

        # No suitable object found
        return None

    @classmethod
    def getstate(cls, obj, event):
        """Return picklable state of the object and its event"""
        return (cls.serialize_object(obj),
                cls.serialize_event(event))

    @classmethod
    def setstate(cls, qApp, obj, event):
        return qApp.sendEvent(cls.deserialize_object(qApp, obj),
                              cls.deserialize_event(event))


def EventRecorder():
    """
    Return an instance of EventRecorder with closure over correct
    (PyQt4's or PyQt5's) version of QtCore.QObject.
    """
    global QtCore

    class EventRecorder(QtCore.QObject):

        QEVENT_EVENTS = {
            # Events that extend QEvent
            # QtCore.QEvent.Close,
            # QtCore.QEvent.ContextMenu,
            QtCore.QEvent.DragEnter,
            QtCore.QEvent.DragLeave,
            QtCore.QEvent.DragMove,
            QtCore.QEvent.Drop,
            QtCore.QEvent.Enter,
            # QtCore.QEvent.FocusIn,
            # QtCore.QEvent.FocusOut,
            QtCore.QEvent.KeyPress,
            QtCore.QEvent.KeyRelease,
            QtCore.QEvent.MouseButtonDblClick,
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QEvent.MouseMove,
            QtCore.QEvent.Move,
            # QtCore.QEvent.Resize,
            # TODO: add non-spontaneous QtCore.QStateMachine.SignalEvent ?
        }

        EventType = {v: k
                     for k, v in QtCore.QEvent.__dict__.items()
                     if isinstance(v, int)}

        def __init__(self):
            super().__init__()
            self.log = []

        def eventFilter(self, obj, event):
            # Only process out-of-application, system (e.g. X11) events
            if not event.spontaneous():
                return False
            is_skipped = event.type() not in self.QEVENT_EVENTS
            log.debug('Caught %s%s %s event: %s',
                      'spontaneous ' if event.spontaneous() else '',
                      'skipped' if is_skipped else 'recorded',
                      self.EventType[event.type()],
                      type(event))
            if not is_skipped:
                self.log.append(Resolver.getstate(obj, event))
            return False

        def dump(self, file):
            log.debug('Writing scenario file')
            try:
                import cPickle as pickle
            except ImportError:
                import pickle
            pickle.dump(self.log, file, protocol=0)
            log.info("Scenario written into '%s'", file.name)

    return EventRecorder()


def EventReplayer():
    """
    Return an instance of EventReplayer with closure over correct
    (PyQt4's or PyQt5's) version of QtCore.QObject.
    """
    global QtCore

    class EventReplayer(QtCore.QObject):

        started = False

        def __init__(self):
            super().__init__()
            self.state

        def eventFilter(self, obj, event):
            if event.type() == QtCore.Qt.ActivationChange:
                self.started = True
                QtCore.QTimer()

            # Only process out-of-application, system (e.g. X11) events
            if not event.spontaneous():
                return False
            is_skipped = event.type() not in self.QEVENT_EVENTS
            log.debug('Caught %s%s %s event: %s',
                      'spontaneous ' if event.spontaneous() else '',
                      'skipped' if is_skipped else 'recorded',
                      self.EventType[event.type()],
                      type(event))
            if not is_skipped:
                self.log.append(Resolver.getstate(obj, event))
            return False

        def dump(self, file):
            log.debug('Writing scenario file')
            try:
                import cPickle as pickle
            except ImportError:
                import pickle
            pickle.dump(self.log, file, protocol=0)
            log.info("Scenario written into '%s'", file.name)

    return EventReplayer()


def main():
    args = parse_args()

    global QtGui, QtCore, Qt, QT_KEYS
    PyQt = 'PyQt' + str(args.qt)
    QtGui = import_module(PyQt + '.QtGui')
    QtCore = import_module(PyQt + '.QtCore')
    Qt = QtCore.Qt
    QT_KEYS = {value: 'Qt.' + key
               for key, value in Qt.__dict__.items()
               if key.startswith('Key_')}
    Resolver.FUZZY_MATCHING = args.fuzzy

    assert 'Qt.LeftButton|Qt.RightButton' == \
           Resolver._qflags_key(Qt, Qt.LeftButton|Qt.RightButton)

    event_filters = []
    recorder = None
    if args.record:
        recorder = EventRecorder()
        event_filters.append(recorder)
    if args.replay:
        event_filters.append(EventReplayer())
    ...

    assert event_filters

    class QApplication(QtGui.QApplication):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for event_filter in event_filters:
                self.installEventFilter(event_filter)

    # Patch QApplication to filter all events through EventRecorder
    QtGui.QApplication = QApplication

    # Execute the app
    args.main()
    # TODO: catch kill signals and propagate them to app

    # Write the "logs"
    if args.record:
        recorder.dump(args.record)

    return 0

if __name__ == '__main__':
    sys.exit(main())
