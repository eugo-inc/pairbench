---
description: "Every environment variable pairbench reads or sets, what it does with it and which software defines it."
---

# Environment variables

pairbench's own environment variables start with `PAIRBENCH_`, and a variable that other
software defines keeps the name that software gives it. This page lists every variable
pairbench reads or sets, what it does with it and which software defines it, then the variables
its showcases and its test suite read.

Each variable has its own heading, so a link can point at it, for example
[`environment.md#pairbench_config`](#pairbench_config). A name written with a trailing `*`
stands for every variable whose name starts that way.

## Your own variables

The names you put in a `launch.env` table or a side's `env` table are yours: pairbench sets
them in the launch as written, and the config written to the capture hides the value of a name
that looks like a credential (see [config](config.md#setting-a-key-without-a-file)).

A variable named in `launch.env_pass` is also yours, for example a model hub token that a
server reads. pairbench hands it to the launch by name and never writes its value anywhere:
the capture and the results hold only the name. On an image or serving side the value travels
in the environment of the engine's command (`--env NAME`), so it does not show on a command
line another user of the machine can list. A command or Python-environment side gets it in its
environment.

pairbench reads no secret of its own. The naming rule covers secrets as well: a token that
pairbench itself reads is named with the same prefix, such as `PAIRBENCH_TOKEN`.

## pairbench's own variables

### `PAIRBENCH_CONFIG`

Defined by pairbench.
The config file to load, as `--config FILE` does. No config file is loaded without one of the
two, because a config launches commands.

### `PAIRBENCH_OUT`

Defined by pairbench.
The run folder, as `run.out` sets it. When `PAIRBENCH__RUN__OUT` is also set, both must name
the same folder, or the run stops with `E_CONFIG` (exit 2).

### `PAIRBENCH__*`

Defined by pairbench.
`PAIRBENCH__SECTION__KEY` sets the config key `section.key`, with double underscores between
the parts of the path: `PAIRBENCH__RUN__ROUNDS=24` sets `run.rounds`. The parts are
lower-cased, and the value is read as a TOML value when it parses as one and as text
otherwise. A variable that names no key stops the run with `E_CONFIG` (exit 2). The command
line wins over the environment, and the environment over the config file. See
[config](config.md#setting-a-key-without-a-file).

### `PAIRBENCH__LAUNCH__ENGINE`

Defined by pairbench.
Sets `launch.engine`, as every `PAIRBENCH__` variable sets its key. When `launch.engine` is
`auto` and both Docker and Podman are found, the engine it names is the one used.

### `PAIRBENCH_WORK_FACTOR`

Defined by pairbench.
Set to `2` in the positive control's launch when `controls.positive_via = "factor"`. The
workload reads it and does its work that many times; every showcase workload does. See
[positive control](../method/positive-control.md).

### `PAIRBENCH_ENV_PAD`

Defined by pairbench.
Set in every launch of a round when `run.vary_env_size = true`: a run of the letter `x`
whose length changes from round to round, so the size of the environment does not stay the
same for the whole run.

### `PAIRBENCH_*`

Defined by pairbench.
Every name with this prefix belongs to pairbench. A command or Python-environment side does
not inherit these variables from the environment pairbench runs in; name one in
`launch.env_pass` to hand it on.

## Variables pairbench reads

### `CI`

Defined by automated pipelines (GitHub Actions, GitLab CI/CD).
A true value (anything but an empty value, `0`, `false`, `no` or `off`) marks the run as one
made in an automated pipeline: the machine record says so, and the quiet-machine wait records
its check without waiting unless asked. See [shared machines](../method/shared-machines.md).

### `PATH`

Defined by POSIX.
Where pairbench looks for `docker`, `podman`, `conda`, `perf`, `nvidia-smi` and the program of
a command or Python-environment side. A virtual-environment or conda side puts its
environment's `bin` folder first.

### `DOCKER_HOST`

Defined by Docker.
When it points Docker's command at anything but a local socket (`unix://...`), pairbench takes
the containers to run elsewhere, so it does not look for their processes on this machine and
does not hand back the files they wrote. It is also one of the
[`DOCKER_*`](#docker_) names the engine's command reads.

### `CONTAINER_HOST`

Defined by Podman.
The same for Podman: when it points Podman's command at anything but a local socket, the
containers are taken to run elsewhere.

### `container`

Defined by container managers (systemd container interface).
A value that is not empty says that pairbench itself runs inside a container. The machine
record says so, and the machine checks work as the table in
[shared machines](../method/shared-machines.md) shows for a run inside a container.

### `KUBERNETES_SERVICE_HOST`

Defined by Kubernetes.
A value that is not empty says that pairbench runs inside a Kubernetes pod, and so inside a
container, with the same effect as [`container`](#container).

### `CONDA_EXE`

Defined by conda.
The `conda` program that looks up a conda side given by name. Without it, `conda` is looked
for on `PATH`.

## Variables the container engine's command reads

Docker's and Podman's own commands read the variables below. On an image or serving side,
pairbench keeps the caller's value of each for the engine's command: a side's `env` entry of
one of these names is passed to the container on the engine's command line
(`--env NAME=VALUE`) instead of through the command's environment, and `env_pass` refuses such
a name with `E_ENGINE_UNSUPPORTED` (exit 3), since its value would then show on a command line.
A name matches in any case: `http_proxy` counts as `HTTP_PROXY`.

### `HOME`

Defined by POSIX.
Read by the engine's own command.

### `TMPDIR`

Defined by POSIX.
Read by the engine's own command.

### `USER`

Defined by login (util-linux).
Read by the engine's own command.

### `HTTP_PROXY`

Defined by Go (net/http).
Read by the engine's own command.

### `HTTPS_PROXY`

Defined by Go (net/http).
Read by the engine's own command.

### `NO_PROXY`

Defined by Go (net/http).
Read by the engine's own command.

### `ALL_PROXY`

Defined by curl.
Read by the engine's own command.

### `SSL_CERT_FILE`

Defined by Go (crypto/x509).
Read by the engine's own command.

### `SSL_CERT_DIR`

Defined by Go (crypto/x509).
Read by the engine's own command.

### `GODEBUG`

Defined by Go (runtime).
Read by the engine's own command.

### `GOGC`

Defined by Go (runtime).
Read by the engine's own command.

### `GOMAXPROCS`

Defined by Go (runtime).
Read by the engine's own command.

### `GOMEMLIMIT`

Defined by Go (runtime).
Read by the engine's own command.

### `GOTRACEBACK`

Defined by Go (runtime).
Read by the engine's own command.

### `DOCKER_*`

Defined by Docker.
Read by the engine's own command.

### `CONTAINER_*`

Defined by Podman.
Read by the engine's own command.

### `CONTAINERS_*`

Defined by Podman.
Read by the engine's own command.

### `BUILDAH_*`

Defined by Podman.
Read by the engine's own command.

### `REGISTRY_AUTH*`

Defined by Podman.
Read by the engine's own command.

### `XDG_*`

Defined by XDG Base Directory Specification.
Read by the engine's own command.

### `LD_*`

Defined by the dynamic linker (ld.so).
Read by the engine's own command.

### `DYLD_*`

Defined by the dynamic linker of macOS (dyld).
Read by the engine's own command.

## Variables pairbench sets in a launch

### `CUDA_VISIBLE_DEVICES`

Defined by CUDA.
Set to the GPUs of `launch.gpus` in a command or Python-environment side's launch, so the
launched program sees only those GPUs; `gpus = "all"` removes it, so every GPU is visible.
Setting it in an `env` table as well as `gpus` is refused with `E_USAGE` (exit 2).

### `CUDA_DEVICE_ORDER`

Defined by CUDA.
Set to `PCI_BUS_ID` beside `CUDA_VISIBLE_DEVICES`, so CUDA numbers the visible GPUs in the
order of their PCI bus ids.

### `PYTHONPERFSUPPORT`

Defined by Python.
Set to `1` in the explain step's sampled-stacks launch, so a Python 3.12 or newer interpreter
reports its function names to `perf`. See [diagnostics](../method/diagnostics.md).

### `VIRTUAL_ENV`

Defined by Python (venv).
Set to the environment's folder for a virtual-environment side; removed for a plain
interpreter or a conda side.

### `CONDA_PREFIX`

Defined by conda.
Set to the environment's folder for a conda side; removed for a plain interpreter or a
virtual-environment side.

### `CONDA_DEFAULT_ENV`

Defined by conda.
Set to the environment's name for a conda side; removed for a plain interpreter or a
virtual-environment side. The environment's activation scripts are not run.

### `PYTHONHOME`

Defined by Python.
Removed from every Python-environment side's launch, so the interpreter uses its own
standard library. A side's `env` table can set it again.

### `PYTHONPATH`

Defined by Python.
Removed from every Python-environment side's launch, so the interpreter sees its own packages.
A side's `env` table can set it again.

## Variables of the showcases and the test suite

The `pairbench` command reads none of these. The `run.sh` scripts of the
[showcases](../showcases.md) and the repository's test suite do.

### `PAIRBENCH_SHOWCASE_ENGINE`

Defined by pairbench.
The container engine command a showcase's `run.sh` calls for its own preparation, such as an
install into a folder the sides mount. `docker` when unset.

### `PAIRBENCH_SHOWCASE_PUBLISH`

Defined by pairbench.
A folder inside the showcase, without `..`: the showcase's `run.sh` then makes a run whose
results may be published. It refuses unless the checkout is reached at `/work`, runs
`pairbench run` with `HOME=/home/user` into a new private folder under `pairbench-runs/`, and
publishes `results.json`, `results.md` and `report.html` into the named folder, and
`hash_inputs.json` with them only when the shared files show every value the sidecar holds;
otherwise the sidecar stays owner-only in the private folder and `run.sh` exits with the run's
own code. A normal run when unset. Each of these values is refused with exit 2 and its own
line on standard error, before anything runs: an empty value; one that names the showcase
folder itself, such as `.` or `./.`; an absolute path or one with `..`; one with a part made
only of blanks or only of dots, or a part that starts with `-`; and `pairbench-runs` or a
folder under it, which holds the private run folders. A value that reaches, through a link, the
showcase folder, a folder that holds it, or `pairbench-runs` or a folder under it is refused the
same way, as is one with a part that is a link leading to no folder.

### `PAIRBENCH_NEIGHBOUR_LOOPS`

Defined by pairbench.
How many busy loops the neighbour container of the noisy neighbour showcase runs. `1` when
unset.

### `PAIRBENCH_TEST_GPU`

Defined by pairbench.
Set to `1` to let the test suite run its GPU tests. Without it they skip, so a machine that
has a GPU does not start GPU work by running the tests.

### `PAIRBENCH_REQUIRE_ENGINE`

Defined by pairbench.
Set to `docker` or `podman` to turn a test's skip for want of that container engine into a
failure.

### `PAIRBENCH_REQUIRE_PLOT`

Defined by pairbench.
Set to `1` to turn a test's skip for want of the `plot` extra into a failure.

### `PAIRBENCH_REQUIRE_DELIVERY`

Defined by pairbench.
Set to `1` to turn the skip of the tests that build and install the wheel, when they cannot,
into a failure.

## Where the definitions come from

Each "Defined by" above names the software whose own documentation or source defines the
variable:

- `CI`: GitHub Actions,
  [variables reference](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)
  ("Always set to `true`"); GitLab,
  [predefined CI/CD variables](https://docs.gitlab.com/ci/variables/predefined_variables/),
  read for GitLab 19.3.
- `HOME`, `PATH`, `TMPDIR`: POSIX.1-2024,
  [Environment Variables](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap08.html).
- `USER`: [login(1)](https://man7.org/linux/man-pages/man1/login.1.html) of util-linux 2.43,
  which sets it from the password entry.
- `container`: systemd,
  [Container Interface](https://github.com/systemd/systemd/blob/v257/docs/CONTAINER_INTERFACE.md)
  at v257: the container manager sets it for the container's first process.
- `KUBERNETES_SERVICE_HOST`: Kubernetes,
  [Accessing the Kubernetes API from a Pod](https://kubernetes.io/docs/tasks/run-application/access-api-from-pod/),
  read for v1.37.
- `DOCKER_*`, `DOCKER_HOST`: the
  [`docker` command reference](https://docs.docker.com/reference/cli/docker/), read for Docker
  29.8, which lists `DOCKER_HOST` and the other `DOCKER_` variables and says the command also
  reads `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY`.
- `CONTAINER_*`, `CONTAINERS_*`, `CONTAINER_HOST`: [podman(1)](https://docs.podman.io/en/v5.4.0/markdown/podman.1.html)
  of Podman 5.4.0, which also lists `TMPDIR` and three `XDG_` variables.
- `BUILDAH_*`: [podman-build(1)](https://docs.podman.io/en/v5.4.0/markdown/podman-build.1.html)
  of Podman 5.4.0.
- `REGISTRY_AUTH*`: [podman-login(1)](https://docs.podman.io/en/v5.4.0/markdown/podman-login.1.html)
  of Podman 5.4.0 (`REGISTRY_AUTH_FILE`).
- `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`: Go,
  [`net/http.ProxyFromEnvironment`](https://pkg.go.dev/net/http@go1.25.0#ProxyFromEnvironment)
  at go1.25.0.
- `ALL_PROXY`: the [curl manual](https://curl.se/docs/manpage.html) of curl 8.23.1.
- `SSL_CERT_FILE`, `SSL_CERT_DIR`: Go, [`crypto/x509`](https://pkg.go.dev/crypto/x509@go1.25.0)
  at go1.25.0.
- `GODEBUG`, `GOGC`, `GOMAXPROCS`, `GOMEMLIMIT`, `GOTRACEBACK`: Go,
  [`runtime`](https://pkg.go.dev/runtime@go1.25.0) at go1.25.0.
- `XDG_*`: the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/0.8/),
  version 0.8.
- `LD_*`: [ld.so(8)](https://man7.org/linux/man-pages/man8/ld.so.8.html) of man-pages 6.19.
- `DYLD_*`: [dyld(1)](https://github.com/apple-oss-distributions/dyld/blob/dyld-1378/doc/man/man1/dyld.1)
  at dyld-1378.
- `VIRTUAL_ENV`: Python, [`venv`](https://docs.python.org/3.13/library/venv.html), 3.13.
- `PYTHONHOME`, `PYTHONPATH`, `PYTHONPERFSUPPORT`: Python,
  [command line and environment](https://docs.python.org/3.13/using/cmdline.html#environment-variables),
  3.13 (`PYTHONPERFSUPPORT` from 3.12 on).
- `CONDA_PREFIX`, `CONDA_DEFAULT_ENV`, `CONDA_EXE`: conda 25.9.1,
  [`conda/activate.py`](https://github.com/conda/conda/blob/25.9.1/conda/activate.py) and
  [`conda/base/context.py`](https://github.com/conda/conda/blob/25.9.1/conda/base/context.py).
- `CUDA_VISIBLE_DEVICES`, `CUDA_DEVICE_ORDER`: the
  [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html),
  v13.5.
