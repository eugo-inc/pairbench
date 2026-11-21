# Third-party notices

The pairbench package bundles no third-party program. The core imports only the Python
standard library. This file lists every tool the package launches or reads, the optional
extras, every test fixture derived from an upstream sample, and the third-party code the
documentation site is built with and carries. Each licence is the one the project's own
repository or documentation states.

## Programs invoked as external programs, not bundled

Each of these is invoked as an external program, not bundled. pairbench runs it only when
you have installed it yourself, and its use is governed by its own licence.

| Program | What pairbench does with it | Licence | Source |
|---|---|---|---|
| Docker | starts image and serving sides | Apache-2.0 | <https://github.com/moby/moby> |
| Podman | starts image and serving sides | Apache-2.0 | <https://github.com/containers/podman> |
| `perf` | the `perf` driver, and counters and sampled stacks in the explain step | GPL-2.0, as part of the Linux kernel source tree | <https://perf.wiki.kernel.org/> |
| `nvidia-smi` | reads GPU state, the GPU witness and power samples | NVIDIA's licence for its driver software | <https://docs.nvidia.com/deploy/nvidia-smi/index.html> |
| Nsight Systems (`nsys`) | `pairbench profile --tool nsys` | NVIDIA's licence for the tool | <https://developer.nvidia.com/nsight-systems> |
| Nsight Compute (`ncu`) | `pairbench profile --tool ncu` | NVIDIA's licence for the tool | <https://developer.nvidia.com/nsight-compute> |
| conda | resolves `conda` sides | BSD-3-Clause | <https://github.com/conda/conda> |
| hyperfine | the `hyperfine` driver | MIT or Apache-2.0 | <https://github.com/sharkdp/hyperfine> |
| Google Benchmark | the `gbench` driver reads its JSON output | Apache-2.0 | <https://github.com/google/benchmark> |
| NVBench | the `nvbench` driver reads its JSON output | Apache-2.0 with LLVM exceptions | <https://github.com/NVIDIA/nvbench> |
| NVBench's summary texts | `tests/fixtures/drivers/nvbench/nvbench.json` keeps the tag, name, description, hint and hide text of each summary word for word, as NVBench 0.1.0 at commit 0f8eb2dd715f90e963a8ab0ff9374097110cc3f9 writes them | Apache-2.0 with LLVM exceptions | <https://github.com/NVIDIA/nvbench/blob/0f8eb2dd715f90e963a8ab0ff9374097110cc3f9/LICENSE> |
| pytest-benchmark | the `pytest-benchmark` driver reads its JSON output | BSD-2-Clause | <https://github.com/ionelmc/pytest-benchmark> |
| llama-bench (llama.cpp) | the `llama-bench` driver reads its JSON output | MIT | <https://github.com/ggml-org/llama.cpp> |
| GuideLLM | the `guidellm` driver runs it against a serving side and reads its report | Apache-2.0 | <https://github.com/vllm-project/guidellm> |
| AIPerf | the `aiperf` driver runs it against a serving side and reads its report | Apache-2.0 | <https://github.com/ai-dynamo/aiperf> |
| vLLM (`vllm bench serve`) | the `vllm-bench` driver runs it against a serving side and reads its results | Apache-2.0 | <https://github.com/vllm-project/vllm> |
| `true` | the empty command that times the cost of a launch | the licence of the system that provides it | your operating system |
| `sysctl` | reads the CPU model on macOS | the licence of the system that provides it | your operating system |

pairbench can call a profiler if you have installed it yourself: a GPU profiler, or `perf`
for counters and sampled stacks. It does not include, download or redistribute one. Your
use of a profiler, and what you may publish from its output, is governed by the licence you
accepted with it. Read it before publishing results. Its output holds names from your code.
The showcases here publish no output of a GPU profiler.

## Optional extras, not bundled

These Python packages are installed only when you ask for the extra. None is bundled.

| Extra | Package | Licence | Source |
|---|---|---|---|
| `plot` | matplotlib, an optional extra that is not bundled | the Matplotlib licence, based on the PSF licence | <https://matplotlib.org/stable/project/license.html> |
| `mcp` | the MCP Python SDK (`mcp`) | MIT | <https://github.com/modelcontextprotocol/python-sdk> |
| `gpu` | `nvidia-ml-py` | BSD-3-Clause | <https://pypi.org/project/nvidia-ml-py/> |
| `llm` | GuideLLM, AIPerf | Apache-2.0 | see above |
| `micro` | pytest-benchmark | BSD-2-Clause | see above |

## The documentation site

The documentation site is built from `docs/` with the packages below. npm installs the
packages of the lockfile in `site/`; of Pagefind's programs, one for each system, it installs
the one for the machine that builds the site. None of them is in the Python package. The
built pages carry the scripts and styles of Astro, Starlight, Expressive Code and Pagefind.
Pagefind's highlighter carries mark.js. Pagefind's search interface carries the Svelte
runtime and the `bcp-47` parser of language tags with the three character tests it uses,
built into the interface's prebuilt scripts, so the site's lockfile does not list them. The
Pagefind program writes the scripts of its component interface into the built site too, with
`adequate-little-templates` and the same `bcp-47` parser built in. The versions of the
packages built into the two interfaces are the ones that Pagefind's own lockfiles for them
install at the version the site locks
(<https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_ui/default/package-lock.json>,
<https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_ui/component/package-lock.json>),
and the source of each is its licence file at that version. `adequate-little-templates` has
no tag for its version, so its source is its licence file at the commit its package was
published from. The site map plug-in runs only while the site is built.

| Package and version | What the site uses it for | Licence | Source |
|---|---|---|---|
| `astro` 7.4.4 | builds the pages; its client scripts are in the built pages | MIT | <https://github.com/withastro/astro> |
| `@astrojs/starlight` 0.42.8 | the theme, the navigation, the table of contents and the search box | MIT | <https://github.com/withastro/starlight> |
| `astro-expressive-code` 0.44.3 | the code blocks and their copy button, through Starlight | MIT | <https://github.com/expressive-code/expressive-code> |
| `pagefind` 1.6.0 | builds the search index and the scripts that read it | MIT | <https://github.com/Pagefind/pagefind> |
| `@pagefind/darwin-arm64`, `@pagefind/darwin-x64`, `@pagefind/freebsd-x64`, `@pagefind/linux-arm64`, `@pagefind/linux-x64`, `@pagefind/windows-arm64`, `@pagefind/windows-x64` 1.6.0 | the Pagefind program for each system, which writes the search index and Pagefind's scripts into the built site | MIT | <https://github.com/Pagefind/pagefind> |
| `@pagefind/default-ui` 1.6.0 | the search interface, through Starlight | MIT | <https://github.com/Pagefind/pagefind> |
| `svelte` 4.2.20 | the runtime of the search interface, inside its prebuilt scripts | MIT | <https://github.com/sveltejs/svelte/blob/svelte@4.2.20/LICENSE.md> |
| `adequate-little-templates` 1.0.2 | renders the markup of Pagefind's component interface, inside its prebuilt scripts | MIT | <https://github.com/bglw/adequate-little-templates/blob/47d207b7840a5e7ea847e1f630454d81ee3ad16e/LICENSE> |
| `bcp-47` 2.1.2 | reads the language tag of a page, so each search interface picks its translation; inside the prebuilt scripts of both | MIT | <https://github.com/wooorm/bcp-47/blob/2.1.2/license> |
| `is-alphabetical` 2.0.1 | a character test of `bcp-47`, inside the same scripts | MIT | <https://github.com/wooorm/is-alphabetical/blob/2.0.1/license> |
| `is-alphanumerical` 2.0.1 | a character test of `bcp-47`, inside the same scripts | MIT | <https://github.com/wooorm/is-alphanumerical/blob/2.0.1/license> |
| `is-decimal` 2.0.1 | a character test of `bcp-47`, inside the same scripts | MIT | <https://github.com/wooorm/is-decimal/blob/2.0.1/license> |
| `@astrojs/sitemap` 3.7.5 | writes the site map while the site is built; none of it is in the built pages | MIT | <https://github.com/withastro/astro/tree/main/packages/integrations/sitemap> |
| mark.js 8.11.1 | highlights the words a search found, inside Pagefind's highlighter | MIT | <https://github.com/julmot/mark.js> |

Pagefind's search programs, `pagefind/wasm.en.pagefind` and `pagefind/wasm.unknown.pagefind`
in the built site, are WebAssembly built from Rust, which the search scripts run in the
reader's browser. They are Pagefind's own crate `pagefind_web`, under Pagefind's licence above,
with every crate it depends on for the WebAssembly target and the crates those depend on, each
at the version that Pagefind 1.6.0 locks
(<https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_web/Cargo.toml>,
<https://github.com/Pagefind/pagefind/blob/v1.6.0/pagefind_web/Cargo.lock>). The lock file also
names crates that are not in the programs: a procedural macro or a build script's dependency,
which runs only while the programs are built, and an optional crate that no enabled feature
turns on. The table lists the crates compiled in, and what the files name in their `producers`
section: the compiler with its standard library, and the tools that made them. The licence of
each crate is the one its own `Cargo.toml` states at that version, and its source is that file.
The compiler's version is given without its build date.

| Crate and version | What it is in the programs | Licence | Source |
|---|---|---|---|
| `bit-set` 0.11.1 | a set of bits, a dependency of `pagefind_web` | Apache-2.0 OR MIT | <https://docs.rs/crate/bit-set/0.11.1/source/Cargo.toml.orig> |
| `bit-vec` 0.10.1 | a vector of bits, a dependency of `bit-set` | Apache-2.0 OR MIT | <https://docs.rs/crate/bit-vec/0.10.1/source/Cargo.toml.orig> |
| `cfg-if` 1.0.4 | a macro of conditional code, a dependency of `wasm-bindgen` | MIT OR Apache-2.0 | <https://docs.rs/crate/cfg-if/1.0.4/source/Cargo.toml.orig> |
| `hifijson` 0.5.0 | reads JSON, a dependency of `pagefind_web` | MIT | <https://docs.rs/crate/hifijson/0.5.0/source/Cargo.toml.orig> |
| `minicbor` 2.3.1 | reads the CBOR of the search index, a dependency of `pagefind_web`; the files name the path of its source, `minicbor-2.3.1/src/decode/decoder.rs` | BlueOak-1.0.0 | <https://docs.rs/crate/minicbor/2.3.1/source/Cargo.toml.orig> |
| `once_cell` 1.21.4 | values set once, a dependency of `wasm-bindgen` | MIT OR Apache-2.0 | <https://docs.rs/crate/once_cell/1.21.4/source/Cargo.toml.orig> |
| `pagefind_stem` 1.0.0 | the stemmer, a dependency of `pagefind_web`; Snowball 3.0.0 wrote its word tables, and the notices of rust-stemmers (MIT) and of Snowball are in its `src/lib.rs` | MIT, and BSD-3-Clause for its Snowball tables | <https://docs.rs/crate/pagefind_stem/1.0.0/source/Cargo.toml.orig>, <https://docs.rs/crate/pagefind_stem/1.0.0/source/src/lib.rs>, <https://github.com/snowballstem/snowball/blob/v3.0.0/COPYING> |
| `unicode-ident` 1.0.24 | tells which characters may make up an identifier, a dependency of `wasm-bindgen-shared` | (MIT OR Apache-2.0) AND Unicode-3.0 | <https://docs.rs/crate/unicode-ident/1.0.24/source/Cargo.toml.orig> |
| `wasm-bindgen` 0.2.129 | the bindings between WebAssembly and JavaScript, a dependency of `pagefind_web` | MIT OR Apache-2.0 | <https://docs.rs/crate/wasm-bindgen/0.2.129/source/Cargo.toml.orig> |
| `wasm-bindgen-shared` 0.2.129 | a part of `wasm-bindgen` shared with its tools, a dependency of `wasm-bindgen` | MIT OR Apache-2.0 | <https://docs.rs/crate/wasm-bindgen-shared/0.2.129/source/Cargo.toml.orig> |
| `write-json` 0.1.4 | writes JSON, a dependency of `pagefind_web` | MIT OR Apache-2.0 | <https://docs.rs/crate/write-json/0.1.4/source/Cargo.toml.orig> |
| `std`, the Rust standard library, and `rustc` 1.101.0-nightly (f9ceb4a4d) | the path of the library's source, `library/std/src/thread/local.rs`, and the compiler in the `producers` section | MIT OR Apache-2.0 | <https://github.com/rust-lang/rust/blob/f9ceb4a4d45a471eed7bd8c40dddb7c38e749e21/library/std/Cargo.toml> |
| `wasm-bindgen` 0.2.129 (165586f85) | a tool in the `producers` section | MIT OR Apache-2.0 | <https://docs.rs/crate/wasm-bindgen/0.2.129/source/Cargo.toml.orig> |
| `walrus` 0.27.2 | a tool in the `producers` section | MIT/Apache-2.0 | <https://docs.rs/crate/walrus/0.27.2/source/Cargo.toml.orig> |

## Test fixtures derived from an upstream sample

| Fixture | Derived from | Licence | Source |
|---|---|---|---|
| `tests/fixtures/serving/vllm-bench/*.json` | the result fields that vLLM's `vllm/benchmarks/serve.py` saves, as of v0.33.0, with synthetic values | Apache-2.0 | <https://github.com/vllm-project/vllm> |

Every other fixture is synthetic, or the output of a real run of a public tool on a public
image; its `*.provenance.json` sidecar says which.
