<!-- Copyright 2024 Michael Käser -->
<!-- SPDX-License-Identifier: (Apache-2.0 OR MIT) -->
# Eventlib-py
[![Release](https://github.com/mickare/eventlib-py/actions/workflows/release.yml/badge.svg)](https://github.com/mickare/eventlib-py/actions/workflows/release.yml)
![PyPI - Version](https://img.shields.io/pypi/v/eventlib-py?label=pypi%20package&color=%2334D058%2C%2328A745)
![PyPI - License](https://img.shields.io/pypi/l/eventlib-py)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/eventlib-py)

Eventlib-py is a small & simple event framework for Python that can be used to decouple your code.

Feature overview:

- **Fast** - Pre-computed event chains for fast event emission.
- **Lightweight** - No extra dependencies.
- **Asynchronous** - Full support for asynchronous event handlers and context managers.
- **Priority Ordering** - Control the order in which event handlers are called.
- **Monitoring** - Use context managers to monitor event processing.

```python
import asyncio
import dataclasses

import eventlib


@dataclasses.dataclass
class MyEvent(eventlib.BaseEvent):
    value: str


@eventlib.subscribe()
async def on_my_event(event: MyEvent):
    print(f"Received: {event.value}")


asyncio.run(MyEvent("Hello, world!").emit_async())  # Prints: "Received: Hello, world!"
```

## Usage

### Event Inheritance

```python
import eventlib


class MyEvent(eventlib.BaseEvent):
    pass


class SubEvent(MyEvent):
    pass


@eventlib.subscribe()
def on_base_event(event: MyEvent):
    print("Received event", event.__class__.__name__)


SubEvent().emit()  # Prints: "Received event SubEvent"
```

### Priority Ordering

```python
import eventlib


class MyEvent(eventlib.BaseEvent):
    pass


@eventlib.subscribe(priority=-1)
def first():
    print("first")


@eventlib.subscribe()  # default: priority = 0
def second():
    print("second")


@eventlib.subscribe(priority=1)
def third():
    print("third")


MyEvent().emit()  # Prints: "first", "second", "third"
```

### Context Managers

```python
import contextlib
import eventlib


class MyEvent(eventlib.BaseEvent):
    pass


@eventlib.subscribe(priority=-1000)  # Ensure that this is called first
@contextlib.contextmanager
def monitor(event: MyEvent):
    print("Event received")
    try:
        yield
    finally:
        print("Event processed")


@eventlib.subscribe()
def on_event(event: MyEvent):
    print("on_event")


MyEvent().emit()  # Prints: "Event received", "on_event", "Event processed"
```

### Asyncio

```python
import asyncio
import contextlib
import eventlib


class MyEvent(eventlib.BaseEvent):
    pass


@eventlib.subscribe(priority=-1000)  # Ensure that this is called first
@contextlib.asynccontextmanager
async def monitor(event: MyEvent):
    print("Event received")
    try:
        yield
    finally:
        print("Event processed")


@eventlib.subscribe()
async def async_on_event(event: MyEvent):
    print("async_on_event")


@eventlib.subscribe()
def on_event(event: MyEvent):
    print("on_event")


asyncio.run(MyEvent().emit_async())  # Prints: "Event received", "async_on_event", "on_event", "Event processed"
```

## Benchmarks

The [benchmark](benchmark/README.md) directory contains code to measure the performance of the eventlib-py library and compare it with a hard-coded reference implementation in Python.

### Benchmark `case_all`

The following table shows the overhead of the eventlib-py library in the [case_all](./benchmark/cases/case_all.py) benchmark.
It's a mixed benchmark with all kinds of sync & async event handlers and context managers.

| Quantile | Hardcoded Time/Event | EventLib Time/Event | Overhead per Call | EventLib Setup |
|:---------|---------------------:|--------------------:|------------------:|---------------:|
| 0.50     |             42.289μs |            45.373μs |               +7% |      135.125μs |
| 0.90     |             43.560μs |            46.809μs |              +10% |      143.000μs |
| 0.99     |             46.658μs |            50.048μs |              +15% |      260.393μs |

The overhead per call is the additional time that is needed to call the event handlers introduced by the eventlib-py library.
The setup time is the additional nonrecurring overhead for subscribing the event handlers in the event system.
It shows that in the **worst case a 15% overhead per call** is introduced.
The expected **median overhead is around 7%** versus hard-coded event handling.


## Development

Use poetry to setup the development environment.

```bash
poetry install --with=dev
poetry shell
```

Run the auto-formatter, checks and linter:

```bash
black .
isort .
mypy .
pylint .
```

Run the tests:

```bash
pytest --cov
```

Performance test:

```bash
pytest -s --runperf  tests/eventlib_tests/test_performance.py
```

## Contributing

Contributions are welcome.

Please follow the commit convention https://www.conventionalcommits.org/en/v1.0.0/.

## License

Dual-licensed under the terms of either the [Apache License 2.0](LICENSE-APACHE) or the [MIT license](LICENSE-MIT).

```
SPDX-License-Identifier: (Apache-2.0 OR MIT)
```
