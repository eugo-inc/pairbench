---
description: "Every key of the TOML config file, with its default and meaning; how a key is set from the command line or the environment."
---

# Config file keys

A config is one TOML file that pairbench reads only when `--config FILE` or the
`PAIRBENCH_CONFIG` environment variable names it; this page lists every key with its default. A
config launches commands, so none is picked up by itself: treat a config from someone else as
code.

- An unknown key is a config error (`E_CONFIG`, exit 2). It is never ignored.
- A duration is a number with `ms`, `s`, `m` or `h`, and parts may be joined: `90s`, `10m`,
  `1h30m`. A bare number is seconds.
- Precedence: the command line, then the environment, then the file, then the defaults.
- `pairbench schema config` prints the JSON Schema of the file.

## Example

```toml
[run]
rounds = "auto"
warmups = 1
same_vs_same = "on"

[workload]
argv = ["python", "bench.py"]
driver = "lines"

[sides.new]
image = "myorg/app:2.0"

[sides.old]
image = "myorg/app:1.9"
baseline = true

[launch]
cpus = "4-7"
env = { OMP_NUM_THREADS = "4" }
env_pass = ["HF_TOKEN"]
timeout = "10m"

[gates]
mode = "warn"

[rule]
name = "strict"

[cases]
primary = ["*"]
```

## Setting a key without a file

- **On the command line**: `--set KEY=VALUE`, for example `--set workload.level_kind=rate`.
  The value is read as a TOML value when it parses as one and as text otherwise.
- **In the environment**: `PAIRBENCH__` followed by the path with double underscores, for
  example `PAIRBENCH__RUN__ROUNDS=24` or `PAIRBENCH__SIDES__NEW__IMAGE=myorg/app:2.1`. The
  parts of the path are lower-cased.
- `PAIRBENCH_OUT` sets the run folder.
- Every variable pairbench reads or sets is listed in [environment variables](environment.md).

The resolved config is written to the capture, with the values of variables whose names look
like credentials replaced by `"<redacted>"`. A variable listed under `env_pass` is forwarded
to the side without its value being recorded.

A name is split into words at `-`, `_`, `.`, where small letters turn to capitals and
between letters and digits. It looks like a credential when it holds `SECRET`, `PASSWORD` or
`CREDENTIAL` anywhere, or when one of its words:

- ends in `KEY`, `KEYS`, `KEYSTORE` or `KEYSET` (`API_KEY`, `apiKey`, `APIKEY`,
  `TINK_KEYSET`), unless the word before is `SORT`, `PARTITION`, `SHARD`, `JOIN`, `FOREIGN`,
  `ROW`, `HOT`, `MULTI`, `MERGE` or `EXISTING` (`--sort-key`, `--multi-key-get`,
  `--merge_keys`, `--use_existing_keys`), which names a key that orders, places or groups data;
- is or ends in `PASS`, `PASSWD`, `PWD`, `PW`, `PASSPHRASE`, `PASSCODE` or `PAT`
  (`KEYSTORE_PASS`, `--storepass`, `MYSQL_PWD`, `--pw`, `GPG_PASSPHRASE`, `GITHUB_PAT`);
- is or ends in `TOKEN` (`HF_TOKEN`, `auth-token`), unless the word is `TOKEN` after `BOS`,
  `EOS`, `PAD`, `UNK`, `SEP`, `CLS`, `MASK`, `STOP`, `SPECIAL`, `FIRST`, `PREFILL` or `SEED`,
  which names one token of a model's vocabulary (`--eos-token-id`, `--seed-token`), or is
  `TOKEN` then `IDS` after
  another word, which names a list of such tokens' ids (`allowed_token_ids`,
  `logprob_token_ids`), unless `API`, `ACCESS`, `AUTH`, `BEARER`, `REFRESH`, `SESSION` or
  `PRIVATE` comes before it, alone or glued to other letters (`api_token_ids`,
  `myapi_token_ids`); `token_ids` alone and `TOKEN_ID` are hidden;
- ends in `TOKENS` after any word, glued to it or not (`APITOKENS`, `HF_TOKENS`), unless
  that word is a count or a size such as `MAX`, `NUM`, `NEW`, `INPUT`, `OUTPUT`, `PROMPT`,
  `TOTAL`, `PREFILL`, `BATCHED`, `QUEUED` or `SCHEDULED` (`--max-tokens`, `num_tokens`,
  `MAX_NEW_TOKENS`, `--max-num-batched-tokens`, `--max-num-queued-tokens`); `tokens` alone is
  shown;
- is `BEARER`, `JWT`, `JWTS`, `CRED`, `CREDS`, `PASSIN` or `PASSOUT` (`--jwt`, `DB_CREDS`,
  `-passin`);
- is `AUTH`, `OAUTH`, `AUTHORIZATION`, `AUTHENTICATE` or `AUTHENTICATION` (`--auth`,
  `BASIC_AUTH`, `--auth-header`, `--authenticate`), or ends in one glued to the letters before
  it (`MASTERAUTH`, `--masterauth`, `BASICAUTH`), unless the next word names a setting of
  it, such as `TYPE`, `MODE`, `METHOD`, `SCHEME`, `PROVIDER` or `TIMEOUT` (`--auth-type`), or
  the first word makes the name a switch, such as `NO`, `ENABLE` or `DISABLE` (`--no-auth`).
  Letters glued before it that make a switch, or `DE`, `RE`, `UN` or `NON`, name no
  credential (`NOAUTH`, `--deauth`);
- is the last word and is `COOKIE`, `COOKIES`, `SIGNATURE`, `SIGNATURES`, `SIG` or `SAS`
  (`--cookie`, `X-Amz-Signature`), unless the first word makes the name a switch
  (`--no-cookies`);
- ends the name of a connection string (`AZURE_STORAGE_CONNECTION_STRING`,
  `connectionString`).

A word in which `KEY` or `TOKEN` is followed by more letters is read as the words written
apart after it, and `TOKEN` also apart from the word before it, so a glued name is hidden as
the same name written apart is: `KEYFILE`, `--keyfile`, `HF_TOKENFILE`, `KEYID`, `KEYPATH`,
`KEYPAIR`, `GPG_KEYRING`, `KEYPEM`, `KEYDATA`, `KEYVALUE`, `TOKENVALUE`, `KEYSTOREFILE`,
`KEYSPATH`, `KEYRINGPATH` and `KEYPAIRNAME` are hidden as `KEY_FILE`, `--key-id`,
`AWS_ACCESS_KEY_ID` and `--key-path` are, while `eostokenid` is shown as `eos_token_id` is.
The word before a key stays glued to it, so `SORTKEY` and `SORTKEYPATH` are hidden though
`sort_key` is shown. A name of the words `TOKEN` and `FILE` written apart and nothing else is
shown (`--token-file`, `TOKEN_FILE`), while `TOKENFILE`, `HF_TOKEN_FILE` and
`--api-token-file` stay hidden. A key or a token followed by a measure that ends the word (see below) is
written apart from the word before it too, so the name is shown as the name written apart is
(`--keysize`, `HFKEYSIZE`, `HFTOKENSIZE`). A word that starts with `KEYBOARD`, `KEYWORD`,
`KEYSPACE`, `KEYFRAME`, `KEYINT`, `KEYNOTE`, `KEYSTROKE`, `KEYPAD`, `KEYMAP`, `KEYCODE`, `KEYSYM`, `KEYBIND`,
`KEYPRESS`, `KEYPOINT`, `KEYSTONE`, `KEYHOLE`, `KEYED`, `KEYLESS`, `KEYCLOAK`, `KEYDB`,
`TOKENIZE`, `TOKENIZATION`, `TOKENIZING`, `TOKENISE`, `TOKENISATION` or `TOKENISING` is read
as that word, so it names no key and no token there (`--keyspace`, `-keyint`,
`tokenizer_path`, `KEYCLOAK_URL`). One of these words that starts with
`TOKEN` is read so wherever it stands (`--detokenize`), and one that starts with `KEY` only at
the start of a word, so after more letters it is a key (`APIKEYWORD` is hidden as
`API_KEY_WORD` is). A key glued at the start of a word to a word that begins like one of these
is read as that word and shown, which the security policy lists as a known limit. A word that
glues `TOKENS` to more letters is hidden when
either `TOKENS` or `TOKEN` written apart there would be (`TOKENSTORE`). A password word
(`PASS`, `PASSWD`, `PWD`, `PW`, `PASSPHRASE`, `PASSCODE` or `PAT`) glued to `FILE`, `PATH`,
`ID`, `PAIR`, `RING`, `VALUE` (each also with an `S`), `DATA`, `PEM`, `HASH`, `HASHES` or
`TEXT`, one or more of them, is read written apart as well: `PASSFILE`, `PGPASSFILE`,
`PWDFILE`, `PASSFILEPATH`, `PASSWDHASH` and `PASSPHRASETEXT` are hidden as `PASS_FILE` is.
A password word glued to any other word is read as one word and shown, which the security
policy lists as a known limit.

Ordinary words that only end like one of these, such as `MONKEY`, `HOTKEY`, `BYPASS`,
`COMPAT` and `SECRETARY`, make no name a credential. The command the shared files show hides
the value of an option by the same test; the next section lists every form it hides.

A `KEY`, `KEYS`, `TOKEN` or `TOKENS` word that a size or a count reads names no credential
either:

- one followed by a measure, a range, a rate, a kind or another treatment of them
  (`KEY_MEASURES`), such as `SIZE`, `LEN`, `LENGTH`, `BITS`, `COUNT`, `NUM`, `MIN`, `MAX`,
  `PREFIX`, `PATTERN`, `RANGE`, `RATE`, `TYPE`, `STDDEV`, `MEDIAN`, `MEAN`, `THRESHOLD`,
  `LIMIT`, `BUDGET`, `PER`, `LATENCY` or `HEALING`, also with `ID` or `IDS` between them:
  `--key-size`, `--keysize`, `--keybits`, `--key-prefix`, `--keys_per_prefix`,
  `--keyrange_num`, `--key_id_range`, `--key-type`, `--token-budget`, `--token-rate`,
  `--token-healing`, `--dbo-decode-token-threshold` and `inter_token_latency` are shown, while
  the id alone names a credential (`--key-id`, `TOKEN_ID`);
- a `KEY`, `KEYS` or `TOKEN` after `MAX`, `MIN`, `NUM`, `TOTAL`, `COUNT`, `MAXIMUM` or
  `MINIMUM` (`KEYS_COUNTED`), or glued to one of the first three: `--max-keys`, `--num-keys`,
  `NumKeys`, `MAX_TOKEN` and `MAXTOKEN` are shown;
- `KEYS` alone: `--keys` is shown.

A word of `CREDENTIAL_LEADS`, `API`, `ACCESS`, `AUTH`, `BEARER`, `REFRESH`, `SESSION` or
`PRIVATE`, anywhere before that word keeps the name a credential, also with other letters glued
to it: `--api-key-prefix`, `--access-token-limit`, `MAX_API_KEYS`, `APIKEYPREFIX`,
`MYAPI_KEY_PREFIX` and `MYAPITOKENIDS` are hidden. `PASS` as the first word of a name and
before `CONFIG` names the passes of a compiler, so `pass_config` is shown, while
`db_pass_config` is hidden.

## What the shared files hide

`results.json`, `results.md` and `report.html` are meant to be shared. They show the command
that was run, for the "how to reproduce" line, with the spec of each `--side` and the value of
each `--set` replaced by `<hidden>` (with `report.include_image_refs` an image reference is
shown), each absolute path, and each relative path that climbs out of its folder with `..`, cut
to its last part, a path whose last part is a home folder, the folder right under `/home` or
`/Users` (`/home/user` or `../home/user`, also as the last path of a list such as
`/usr/bin:/home/user`) or a home written `~made-up-user`, cut to `<hidden>`, as that folder is
named after its user, and the secret part of each form on this list
replaced by `<hidden>`. The capture, `capture.jsonl`, keeps the command as typed: it is private
to the person who ran the benchmark, and pairbench creates it readable and writable by its
owner only (mode `0600`), as it does the files that hold what each process, load step and
server printed. After every run that
writes results, `pairbench run` prints one note on standard error that points here;
`pairbench compare` prints it when it writes results files or prints the results document.

**Where an absolute path ends.** An argument that starts as an absolute path is a path to its
end, blanks included, so a folder named in words is cut with the rest (`/srv/Zq One Two/x.txt`
shows `x.txt`). In a text of several words, such as a shell text or a case id, a path runs on
over the words after it that start with a letter, a digit or `_`, up to the last that holds a
`/`, and the words it runs over are cut with it. A quote ends a path, and so does a word that
starts with any other character: `sh -c 'python3 /made/up/bench.py run fast models/x.gguf'`
shows `sh -c 'python3 x.gguf'`, while `sh -c 'python3 "/made/up/bench.py" run fast models/x.gguf'`
shows `sh -c 'python3 "bench.py" run fast models/x.gguf'`. A word that holds `://` writes an
address and ends a path too: `run /made/up/a.py fast unix:///made/up/s.sock` shows
`run a.py fast unix:///s.sock`. A path in the query of an address runs on in the same way
(the case id `get https://h.example/p?next=/made/up/Zq dir/d` shows
`get https://h.example/p?next=/d`), and the address ends at the first blank that no such path
runs over, so the words after it are read as any others. A relative path that climbs out of
its folder with `..` may name a folder outside the run folder, so it is read and cut as an
absolute path is, wherever the climb stands in it: `../../Zq Files/in.csv`, `./../a/in.csv` and
`data/../../a/in.csv` each show `in.csv`. One that stays inside its folder, such as `a/../b`, and
`..` parts alone, as in `cd ../..`, show as typed. In the query of an address in the shown
command, a climbing path and a `file:` address show their folders where a path before them runs
over them, and a path that starts with three `/` shows whole, as the
[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say; a case id cuts them. In
a case id, a path that starts with two `/` or more at the start of the id or after a blank is
cut like one that starts with a single `/` (`run //made/up/in.bin` shows `run in.bin`). A path
also starts at three `/` or more after one of `[`, `=`, `,`, `;`, `(`, `{`, `@` or a quote
(`test_read[///made/up/in.bin]` shows
`test_read[in.bin]`), and at two `/` or more after the `/` that ends a part of a name when two
more parts follow (`BM_Read///made/up/in.bin` shows `BM_Read/in.bin`). After `:` the `/` start
an address (`file:///made/up/in.bin` shows `file://in.bin`), and two `/` after one of the other
marks start the path at the second (`test_read[//made/up/in.bin]` shows `test_read[/in.bin]`).
The [security policy](../../SECURITY.md#known-limits-of-the-shown-command) lists the forms of a path
that are not read as you may mean them.

**Case ids that read alike once their paths are cut.** Two case ids can differ only in the
words a path runs over: `python3 /made/up/run.py fast data/x` and
`python3 /made/up/run.py slow data/x` both read as `python3 x`, and
`copy /made/up/in.bin at 4 KiB/s` and `copy /made/up/in.bin at 8 KiB/s` both read as `copy s`.
When the cut of an id drops a word that holds no `/`, the name the results show is the cut id
plus a mark: a space, `+` and eight hex digits, as in `python3 x +3c5e7a91` and
`python3 x +b04d2f68`. The mark is the start of an HMAC-SHA256 keyed with a random key the run
draws, taken over a hash of the words of the id that hold no `/`, read with its secrets hidden.
Two ids that differ in such a word get two marks, and an id gets the same mark in every launch,
on every side and in every twin of the run, whatever folder its path names and in whatever
order the launches give the cases, so the results pair each case with itself. A cut that drops
only words that hold a `/` adds no mark: `read /made/up/in.csv` shows `read in.csv`. Nor does a
folder named with a blank in a secret written as a path: `test_db[token:/made/Zq dir/x.pem]` and
`test_db[token:/made/up/x.pem]` both show `test_db[token:<hidden>]`. A word that
writes a `/` as `%2F` holds no `/`: `run /made/up/a.py 4%2Fq data/x` and
`run /made/up/a.py 5%2Fq data/x` show as `run x` with two marks. A path written with `%2F`
from its start, with no letter, digit, `_`, `%`, `.`, `~` or `-` right before it, is cut to
`%2F` and its last part wherever it stands, and its folders are read as folders, so they add no
mark: `copy --in=%2Fmade%2Fup%2Fin.bin` shows `copy --in=%2Fin.bin`, and
`get[?host=%2Fmade%2Fup%2Frun]` shows `get[?host=%2Frun]`. A blank ends such a path, so the
words of a folder named with blanks show (`get[?host=%2Fmade%2FZq dir%2Frun]` shows
`get[?host=%2FZq dir%2Frun]`) and two sides whose folders differ there are refused with
`E_CASES_DIFFER`; written with `%20` for each blank, the folder is cut with the rest and the
sides pair the case.

The run writes its key once to the private capture, before the first name with a mark, with a
hash of each id as read; no flag, environment variable, config key or file sets the key. The
shared files hold neither the key nor any hash of an id. `pairbench compare` of several
captures shows each case by the name the first capture given makes with its key, and makes the
marks of the other captures again with that key from the hashes they keep. Pooled captures
whose ids differ only in a folder or a secret are read as one case; if those folders are
different inputs, keep the captures apart. A note on standard error and in the results says
so, `pool_folders_merged` or `pool_secrets_merged`, naming the case and never the words.

Two ids of one launch that differ only in a hidden secret are refused with `E_USAGE`:
`python3 /made/up/run.py token=made-up data/x` and `python3 /made/up/run.py token=made-up-2 data/x`
read as one name once their path is cut and their secrets hidden, and nothing else tells them
apart. Two that differ in a hidden secret and in a word that holds no `/` get two marks, and an
id whose secret alone differs from one launch, side or twin to the next is read as the same
case. Two ids of one launch that differ only in words that hold a `/`, or in the folders of a
path written with `%2F`, their secrets hidden, are refused too, as pairbench reads such parts as
folders, which may differ between sides and launches, and so are two that differ only in the
spaces between the words a cut drops. An id whose cut already ends like a mark is refused, and so are two ids that a run's
key gives the same mark. A folder whose name holds three or more words and differs between
sides in a word in the middle gives the id a word that holds no `/`, so each side names the
case with another mark: a run refuses that for a primary case with `E_CASES_DIFFER`, and says
so in a `case_named_apart` note for any other case. Give such cases names that differ before
the path, or put the path in quotes: `python3 "/made/up/run.py" fast data/x` shows
`python3 "run.py" fast data/x`.

**What a mark does not do.** A mark is made with its run's key, so captures analysed apart can
show one case with different marks: each new run, and each new compare of result files, draws a
new key, and a pool shows the marks of the first capture named. `pairbench fill` refuses with
exit 7 (`E_FIGURE_MISSING`) a token whose case carries a mark the results it reads do not show,
as when the document was filled from one capture and is filled again from another analysed
apart: pool the captures with one `pairbench compare`, or fill from the results of the same
capture. A pattern given with `--case`, `cases.primary` or `cases.groups` matches a name with or
without its mark; a mark copied from another run's results matches no case of this run, so give
the name without its mark.

**A short plain password in any other form still shows.** A short plain value that nothing on
this list names cannot be told apart from an ordinary value: one given after an option of one
letter (`mytool -k VALUE` shows `VALUE`), as a plain argument or in the path of an address is
shown. Secrets belong in environment variables: set the variable where you run pairbench and
list its name under
`launch.env_pass`, which forwards it to the side without recording its value.

The hashes the shared files show of each side and of the config are computed with these forms
hidden too, so a guess at a hidden value cannot be checked against them. One of them is
narrower there: an address keeps its host in the hashes. A value in any other form is in the
hashes as typed, and someone who knows the rest of the command can confirm a guess at it by
hashing the guess. The case patterns of the config, given with `--case` or as `cases.primary`
or `cases.groups`, are in the hash of the config as typed, as the
[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say.

**What the hash of an `identify` output hides.** An `identify` command prints what tells one
build of a side from another, so its output is hashed with only its credentials hidden, line by
line: a credential-like name given a value (`API_TOKEN=<hidden>`, `password: <hidden>`,
`{"token": "<hidden>"}`), the value after a credential-like option (`--token <hidden>`), a
credential header (`Authorization: <hidden>`), a `user:password` and the password options of a
client, and the user part of an address (`https://<hidden>@made-up.example/x`). No rule of shape
applies there: a checksum (`sha256sum model.bin`, `md5sum model.bin`), a build id
(`Build ID: ...`) and any long or random-looking value stay in the hash, so a change in them
changes `identify_sha256` and the side's fingerprint, and captures made before and after it do
not pool (`E_POOL_SIDE_DRIFT`). A version is no credential, whatever the name of its package
reads like. The pin that starts a line stays in the hash: `keyring==24.3.0` as `pip freeze`
prints it, `keyring == 24.3.0`, and `- keyring=24.3.0=pyh1a2b3c_0` as `conda env export`
prints it; what follows it on the line (`# via`, a marker, a `\`, an option) is read as any
other text, so `keyring==24.3.0 --token <hidden>`. So does a line of a name and a version with
two numbers or more after a colon and nothing else (`keyring: 24.3.0`), a quoted name and such
a version in a table (`{'keyring': '24.3.0'}`), and a line that names a digest and gives one
(`SECRET_SHA256=` and the hexadecimal digits of a digest, `password_hash: bcrypt`).
`keyring=24.3.0` alone is hidden, as a variable is, and so is a number with no dot after a
colon (`password: <hidden>`). A credential an identify command prints
in any other form, a bare token on a line of its own for example, is in the hash as printed.

Every form holds where it stands, inside one argument that holds several words, such as the
text after `sh -c`, and inside a quoted word of it. The name of a hyperfine case made from a
command's text is cleaned the same way. A case id that a driver reads hides the value of a
credential-like name or option, a password before a host written without a scheme and a long
random-looking value, each up to where its part of the id ends at a blank, a `/`, a `,`, a `;`
or a bracket: `test_db[PGPASSWORD=made-up]` shows `test_db[PGPASSWORD=<hidden>]`. A password
before a host is hidden up to the `@`, and the text before its user and after its host is kept,
as where pytest joins it to another value with `-`: `test_db[bob:made-up@db.example:5432-ro]`
shows `test_db[bob:<hidden>@db.example:5432-ro]`, and `test_db[{"dsn":"bob:made-up@db.example"}]`
shows `test_db[{"dsn":"bob:<hidden>@db.example"}]`; such a password holds no `@`, quote or angle
bracket. In a part that also gives a credential-like name a value with `=` after the host, the
password before the host shows, as the
[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say. A credential-like name glued to its value with `:` loses the value the same way
(`test_db[token:made-up]` shows `test_db[token:<hidden>]`), also after another name's `:` or
`=`, after the `-` that joins two values and in quotes, as JSON writes a key
(`test_db[5432-password:made-up]` shows `test_db[5432-password:<hidden>]`, and
`test_api[{"token":"made-up"}]` shows `test_api[{"token":"<hidden>"}]`), except a whole number
right after the `/` that joins two parts of a name, which is a benchmark's named argument:
`BM_Hash/key:3` is shown as it is. A `::` gives no value, so `bench[Token::Kind]` is shown as
it is. After a scheme word such as Basic or Bearer, the token after the blank is
hidden too: `bench[tool --auth=Basic made-up]` shows `bench[tool --auth=<hidden> <hidden>]`. The words in
a pair of brackets, and the words of an id with no bracket, are read as the words of one
argument of a command, with the same rules: `bench[redis-cli -a made-up PING]` shows
`bench[redis-cli -a <hidden> PING]`, `test_db[--password made-up]` shows
`test_db[--password <hidden>]`, and a header or a name before a colon that names a credential hides
the rest of the words in its brackets, an ordinary value included, as it would in one argument
(`bench[tool key: 3]` shows `bench[tool key: <hidden>]`). An option that names no credential
keeps the word after it (`bench[tool --token-count 8]`, `bench[mysql -P 3306]`), and words
outside the brackets of an id that has brackets are read only part by part. A program's text
in the brackets is read as the shown command reads it, so a credential's value it gives as a
string is hidden: `bench[python -c "password = 'made-up'"]` shows
`bench[python -c "password = '<hidden>'"]`. A refusal that names a case id, such as the
refusal of a value that is not a finite number, of a case printed twice or of a hyperfine run
that failed, names it as the reports show it, in `results.json` and `results.md` too, and a refusal of a `--case` pattern
that matches no case names the pattern with the same forms hidden.

A shell text is read as a shell reads it. It is the text after `-c` when the program before it
is a shell (`sh`, `bash`, `dash`, `zsh`, `ksh`, `mksh`, `ash`, `yash` or `fish`), also after a
group of options that holds `c` (`sh -ce`), even when it is one word and also inside another
shell text (`bash -c "sh -c '...'"`). It is also a command text that the program before it
hands to a shell: the remote command of `ssh`, the commands of `hyperfine`, `watch` and
`parallel`, the command of `tmux` given as one argument, with blanks or none, the value of
`gcloud ... --command`, and the text of `-c` or `--command` of `su`, `runuser`, `flock` and
`script`, as their manuals say
([tmux(1) at 3.5a](https://github.com/tmux/tmux/blob/3.5a/tmux.1),
[watch(1) at procps-ng 4.0.5](https://gitlab.com/procps-ng/procps/-/blob/v4.0.5/man/watch.1),
[su(1)](https://github.com/util-linux/util-linux/blob/v2.41/login-utils/su.1.adoc),
[runuser(1)](https://github.com/util-linux/util-linux/blob/v2.41/login-utils/runuser.1.adoc) and
[flock(1)](https://github.com/util-linux/util-linux/blob/v2.41/sys-utils/flock.1.adoc) at
util-linux 2.41, whose
[`script` source](https://github.com/util-linux/util-linux/blob/v2.41/term-utils/script.c) runs
its command with the shell's `-c`). So `tmux new -d 'API_KEY=VALUE&&./bench-old'` shows
`tmux new -d 'API_KEY=<hidden>&&./bench-old'`, and `su bench -c 'API_KEY=VALUE&&./bench-old'`
shows `su bench -c 'API_KEY=<hidden>&&./bench-old'`. The `-c` of `watch` is its colour option,
also last in a group of short options (`watch -tc`), so the word after it is the command:
`watch -c 'API_KEY=VALUE&&./bench-old'` shows `watch -c 'API_KEY=<hidden>&&./bench-old'`. The
`-c` of `su`, `runuser`, `flock`, `script` and `fish` counts last in a group of short options
too: `script -qc 'API_KEY=VALUE&&./bench-old'` shows
`script -qc 'API_KEY=<hidden>&&./bench-old'`. The
text of `env -S` is no shell text, as `env` splits it into words and starts no shell, and nor
is the command of `watch -x` or `--exec`, `hyperfine -N` or `--shell none`, or `parallel -q` or
`--quote`, which they run with no shell: `env -S 'tool --api-key=VALUE&&./bench-old'` shows
`env -S 'tool --api-key=<hidden>'`, while `ssh made-up-host 'tool --api-key=VALUE&&./bench-old'`
shows `ssh made-up-host 'tool --api-key=<hidden>&&./bench-old'`. Such an option counts in a
group of short options too (`watch -tx`), and `hyperfine` takes its options after its commands
as well, so `-N` or `--shell none` anywhere on its command line runs none of them in a shell.
Only a word of its own command line counts: the `-N` inside one of its commands
(`hyperfine 'ssh -N made-up-host true' TEXT`) is an option of that command, and both commands
run in a shell. A quoted word of a text run with no shell that is the text of a shell is a
shell text of its own, so a value there ends at its operators, glued or not:
`env -S 'sh -c "API_KEY=VALUE&&./bench-old"'` shows
`env -S 'sh -c "API_KEY=<hidden>&&./bench-old"'`, and so does that text after
`hyperfine -N`: `hyperfine -N 'sh -c "API_KEY=<hidden>&&./bench-old"'`. Each word of the
command of `watch -x` or `parallel -q`, and of a `tmux` command given as several arguments,
is one argument of the program, read as any other argument is:
`watch -x tool 'DB_PASSWORD=VALUE more'` shows `watch -x tool 'DB_PASSWORD=<hidden>'`.
In a shell text an operator
outside quotes ends a command: `&&`, `||`, `;`,
`&`, `|` or a line break. A hidden value ends there, and the operator and the command after it
are shown and read afresh: `sh -c 'tool --api-key=<hidden>&& ls -l'`,
`sh -c "curl -H 'Authorization: <hidden>'; ls -l"`. A backslash right before a line break,
outside quotes, joins the two lines as a shell does: that line break ends no command, and the
next line goes on with the word or the command before it. A `)` or backquote at the end of a word,
outside quotes and not escaped, closes a command too, and is shown after a hidden value:
`sh -c '(redis-cli AUTH <hidden>) && ./bench'`, `sh -c 'echo $(redis-cli AUTH <hidden>) done'`;
one escaped or inside quotes is part of the value, and so is one in an argument that no shell
reads. A word that starts with `#` outside
quotes starts a comment, which ends the command before it too and is shown as typed, except
for every credential form inside it. When the command right before the comment is a client's
command, the words of the comment are read as words given to that client:
`sh -c 'redis-cli PING # -a VALUE'` shows
`sh -c 'redis-cli PING # -a <hidden>'`, and `sh -c 'redis-cli PING #AUTH VALUE'`, with the
client's command glued to the `#`, shows `sh -c 'redis-cli PING #AUTH <hidden>'`. In any
comment, a form that the argument of any program hides is hidden:
`sh -c './bench # --token VALUE'` shows `sh -c './bench # --token <hidden>'`. The other words
of the comment are shown: `sh -c 'redis-cli AUTH <hidden>  # log in'`. Where the command waits for a value, the
word glued to the `#` is hidden as that value, since the text holds it whether or not the
shell drops it: `sh -c 'redis-cli -a <hidden> PING'` for `-a #VALUE PING`, and after the
password of `AUTH` it is hidden as well (`AUTH <hidden> <hidden> in` for `AUTH VALUE #log in`). A
`#` inside a word (`app#1`), inside quotes or after a backslash starts none. An operator inside quotes or after a
backslash is part of the value (`sh -c "curl -H 'Cookie: <hidden>' http://localhost/x"`), a
redirection such as `2>&1`, `>out` or `>|out` ends no command and is no word of it, so the option
before it still takes the word after it, and the user part of an address is hidden whole,
operators and all (`https://<hidden>@<hidden>/x`). A quoted word that is the text of a shell
in turn is a shell text of its own, where an operator outside its own quotes ends a value too:
`sh -c 'sh -c "API_KEY=<hidden>&&./bench"'`.

Any other argument is read as the program gets it, and an operator in it is part of the value
it stands in: `curl -H 'Cookie: a=1; sid=made-up'` shows `curl -H 'Cookie: <hidden>'`, and
`tool --opts '--x 1 --token=made|up --y 2'` shows `tool --opts '--x 1 --token=<hidden> --y 2'`.
An argument whose first word gives a credential-like name a value is that value to its end,
operators and all, as the first form below says (`tool 'DB_PASSWORD=a b; ls'` shows
`tool 'DB_PASSWORD=<hidden>'`).

### Forms named by the command

- **A credential-like name.** The value given to a variable or an option whose name looks
  like a credential, by the test above, is hidden, whether it stands alone
  (`API_TOKEN=<hidden>`), follows the option (`--api-key=<hidden>`, `--token <hidden>`) or is
  glued to one (`--env=MY_TOKEN=<hidden>`, `-eMY_TOKEN=<hidden>`). Such a value is hidden to
  the end of its argument, spaces included (`env 'DB_PASSWORD=a b c' true` shows
  `env 'DB_PASSWORD=<hidden>' true`), except in a command text, whose next words are read as
  words, as [texts read word by word](#texts-read-word-by-word) says. The test of the name
  ignores case, and a name with a `-` or a `.` gets it too: `password=`, `Api-Key=` and
  `db.password=` hide their whole value. Which of its words still tell two sides apart is
  said in [hidden values that tell two sides apart](#hidden-values-that-tell-two-sides-apart).
  After `--token` the next argument is hidden unless it is another long option. A value that is
  an Authorization scheme word, `Bearer`, `Basic` or `Token` in any case
  (`AUTH_SCHEME_WORDS`), is followed by its token, and the token is hidden too unless it starts
  an option: `tool --token Bearer VALUE -n 8` shows `tool --token <hidden> <hidden> -n 8`, and
  `tool --auth=Basic VALUE` shows `tool --auth=<hidden> <hidden>`. A switch whose name looks like a credential but takes no
  value hides nothing after it: `--allow-credentials` and `--return-tokens-as-token-ids`, and
  their `--no-` forms (`CREDENTIAL_SWITCHES`), which vLLM declares as switches
  ([`vllm/entrypoints/common/cli_args.py` at v0.33.0](https://github.com/vllm-project/vllm/blob/v0.33.0/vllm/entrypoints/common/cli_args.py)),
  so `vllm serve --allow-credentials org/model-a` shows the model.
- **An axis named `Key` or `Keys`.** After `-a` or `--axis`, which set an axis of an NVBench
  benchmark
  ([`docs/cli_help.md`](https://github.com/NVIDIA/nvbench/blob/0f8eb2dd715f90e963a8ab0ff9374097110cc3f9/docs/cli_help.md)),
  or glued to them, a value that gives the axis `Key` or `Keys` its values, with or without
  flags in brackets, is shown with only its random-looking parts hidden: `-a Key=I32`,
  `-a 'Key[pow2]=[8:16]'`, `--axis=Key=I32`, `-aKeys=4`. A value after the option is shown
  so in the text after `sh -c`, in a shell text inside it, in the remote command of `ssh` and
  in the quoted text of an option (`--opts '-a Key=I32'`), shown and hashed alike. This holds
  for every program but the clients of the password table below, whose `-a` takes a password
  (`redis-cli -aKey=V` shows `-a<hidden>`), and the shell builtins `declare`, `local`,
  `readonly` and `typeset`, whose `-a` makes an array: in `declare -a KEY=<hidden>` the value
  is hidden as any credential-like name's is. A credential-like name given a value after the
  axis's values is still hidden: `-a 'Key=I32,TOKEN=<hidden>'`. In the string of a program
  that no shell reads, as the one after `python -c`, `Key=` is read as any other
  credential-like name is, and its value is hidden.
- **A credential setting.** After `set`, `config` or `setenv` (`SETTING_WORDS`), in any case,
  and any options after it, the next word names a setting. When the last part of that name,
  after its last `.`, `:` or `/`, looks like a credential, each later word of the command that
  is no option is hidden whatever its shape, and so is the value glued to a long option after
  its `=`: `aws configure set aws_secret_access_key <hidden>`,
  `git config --global github.token <hidden>`, `redis-cli CONFIG SET requirepass <hidden>`,
  `setenv HF_TOKEN <hidden>`, `gh secret set MY_TOKEN --body <hidden>`. A variable the shell
  puts in the name is read as part of it, so `profile.${PROFILE}.aws_secret_access_key` and
  `//${REGISTRY}/:_authToken` name credentials too. A name that ends in
  `auth` names a credential setting too (`redis-cli CONFIG SET masterauth <hidden>`), and a
  name that ends in `file`, `path` or `dir` names a file or a folder, whose value is a path and
  is shown as the rules for paths say (`redis-cli CONFIG SET tls-key-file certs/redis.key`),
  unless a credential word follows it (`tls-key-file-pass <hidden>`). A `set` right after
  `secret` or `secrets` (`SECRET_SETTING_WORDS`), in any case, sets a secret, so the setting is
  a credential whatever its name: `gh secret set MY_NAME --body <hidden>`, `-b <hidden>`,
  `--body=<hidden>`, and a name written with its value loses the value
  (`fly secrets set MY_NAME=<hidden>`). An option there before the name leaves the name
  unknown, so every later word that is no option is hidden
  (`gh secret set --repo <hidden> <hidden> --body <hidden>`). An option and a bare `=`
  stay shown, so the value of any option after the name is hidden too
  (`--profile <hidden>`), up to a separator, a line break, or the `)` or backquote that closes
  the command. `credential.helper store` and
  `user.name NAME` stay shown, and `--` ends the setting. After `redis-cli`,
  `valkey-cli`, `redis-benchmark` or `valkey-benchmark` (`DATA_SET_CLIENTS`), `SET` writes the
  value of a key and starts no setting when it is the client's command, its first word that is
  no option and no value of an option (`redis-cli -h 127.0.0.1 SET key value`). `CONFIG SET`
  starts one, and so does a `set` of a later command, after a separator or a line break. A
  line break ends the options of `set` too, so `set -e` on its own line names no setting. A
  credential-like word
  anywhere else hides nothing after it, so a benchmark or file name (`./bench sort_by_key 64`,
  `./bench api_key.pem out.json`) and a subcommand (`gh auth token`,
  `kubectl create secret generic NAME`) keep the next word. A setting whose credential word is
  not the last part of its name (`token.made-up-repo`), and a setting after an option that takes
  a value of its own (`config --file made-up.cfg api_key VALUE`), hide their value only by its
  shape.
- **A header.** The value of a header whose name is `Authorization`, `Proxy-Authorization`,
  `Cookie` or looks like a credential: `-H 'Authorization: <hidden>'`. An argument of
  `redis-cli`, `valkey-cli`, `redis-benchmark`, `valkey-benchmark` or `memtier_benchmark` that
  is one word with no blank is a key of the data store, not a header, and is shown as typed:
  `memtier_benchmark --key-prefix auth:`. In a shell text or a command written as one text, such
  a word is read as a header and hides the rest of its command:
  `sh -c 'memtier_benchmark --key-prefix auth: VALUE'` shows `auth: <hidden>`.
- **The user part of an address**: `postgres://<hidden>@<hidden>/db`.
- **A `user:password` value.** The password after `-u`, `--user`, `-U` or `--proxy-user`, and
  after `--cert` or `--proxy-cert` (`certificate:password`), given as the next argument or
  glued to the option, for any program: `curl -u bench:<hidden>`,
  `curl --proxy-user=bench:<hidden>`. A value there that is an address with a user part loses
  only that part, so its host, port and path stay as the rules for an address say:
  `redis-cli -u redis://<hidden>@localhost:6379/0`.
- **A credential query value.** The value of a query parameter whose name looks like a
  credential ends at the next `&` or `#`, so the parameters after it stay:
  `http://localhost:8000/v1?token=<hidden>&threads=8`.
- **A value in the text of a program.** A credential-like name given a value in code keeps the
  name and loses the value: `os.environ['API_KEY'] = '<hidden>'`, `{"api_key": "<hidden>"}`,
  and `API_KEY = <hidden>` for a value of several pieces such as `os.getenv('X', '...')`. After
  a bare name, the value of `=` or `:` starts on the same line, so a word on the next line is
  no value of it. A name with `:` right after `if`, `elif`, `while`, `for`, `in`, `with`, `as`,
  `except`, `lambda`, `not`, `and`, `or`, `is`, `case` or `match` (`CODE_KEYWORDS`) is given no
  value, so the statement after it stays: `python3 -c 'if token: run_old()'` is shown as typed.
  A value in quotes ends at its closing quote, and a quote after a backslash does not close it,
  but in the single quotes of a shell text, which hold no escape. A value that opens with three
  quotes, as a string of Python may, ends at the three that close it, so a quote, a `;` or an
  `&&` inside it is hidden with it. In a shell text, where three quotes are an empty string
  and the opening quote of the next, the value runs at least to the end of the shell word:
  `sh -c "API_KEY='''a'b''' VALUE' ./bench-old"` shows `sh -c 'API_KEY=<hidden> ./bench-old'`.
  A value in backquotes, a template string of JavaScript or a
  command of Perl or of a shell, ends at the backquote that closes it, blanks and `${...}`
  parts included, and one that is not closed runs to the end of the text:
  `` sh -c 'API_KEY=`echo made VALUE` ./bench-old' `` shows
  `sh -c 'API_KEY=<hidden> ./bench-old'`, and
  `` node -e 'process.env.API_KEY = `made VALUE`;run_old()' `` shows
  `node -e 'process.env.API_KEY = <hidden>;run_old()'`. What is glued after the closing
  backquote is more of the same value and is hidden with it:
  `` ./bench --config '{password: `a`VALUE}' `` shows `./bench --config '{password: <hidden>}'`.
  A bare value holds a `;` that no blank
  follows and a closing bracket, as a password may, unless the `;` is an operator of a shell
  text or the bracket closes one open before the value:
  `tool --config '{password: a;b, threads: 8}'` shows
  `tool --config '{password: <hidden>, threads: 8}'`, inside `sh -c` too. A bare value also
  runs on past a line break after a backslash, as a shell joins the two lines in double quotes
  and a program joins them in its text. In the text after `-c` of a program that is no shell
  (`python -c`), the statement after a quoted value stays, as do an `&&`, a `|` or a backquote
  right after its closing quote, and a header-like `name:` hides its value up to the end of its
  line: in `python3 -c 'API_KEY="VALUE";run_old()'` the quoted value is hidden and `run_old()`
  stays. A `||`, which joins two strings in SQL, and an `&&` or a `|` that a quote follows go on
  with the value, so the rest of the word is hidden with it:
  `psql -c "ALTER ROLE app PASSWORD='made'||'VALUE'"` shows
  `psql -c 'ALTER ROLE app PASSWORD=<hidden>'`. The text after `node -e` or `perl -e` is read as
  any other argument, as Perl and JavaScript end a string where Python does not (Perl's
  `q{...}`, a pattern in either): a value glued to its name there hides the rest of the text,
  so `node -e 'API_KEY="VALUE";run_old()'` shows `node -e 'API_KEY=<hidden>'`.
  A value written as a string that a mark of its own opens is hidden to the mark that closes
  it: a string with a prefix (`f'...'`, `rb"..."`, `@"..."`, `u8"..."`), a raw string of Rust
  (`r#"..."#`), a raw string of C++ with a prefix before its `R` or none (`R"(...)"`,
  `u8R"(...)"`, `LR"x(...)x"`), a quote-like word of Perl or a `%` word of Ruby (`q{...}`,
  `qq/.../`, `%w[...]`), a pattern (`m/.../`, `s/.../.../`), a string in backquotes or in three
  quotes, and a here-document, which runs to the line that holds its end word (`<<EOT` or
  `<<\EOT` up to `EOT`, `<<<EOT` of PHP). After a name of Perl (`$token`, `$ENV{TOKEN}`) a
  quote-like word takes any mark, as Perl does, with blanks before it or not: `$token = q%...%`
  and `$token = q {...}` hide the whole string. A pattern in `/` alone is read so for a name given
  its value as a program gives it, with a blank, a `$` or another sign between them
  (`$token = /.../`, `token =~ /.../`, `token != /.../`). A string after the value, with
  blanks, `.` or `..` between them, is part of it, so `token = 'made' '...'` and
  `$token = 'made' . '...'` hide both strings, and so is a quote-like word after a string and
  a `.`, or a string after a quote-like word: `$token = q{made} . '...'` hides both. So is a
  string on the next line after a `.`, `..` or `+` that ends a line or starts the next one, or
  after a backslash that ends a line and carries the statement on: in
  `token = 'made ' \`, then `'...'` on the next line, both strings are hidden. A line break
  with none of these ends the value. A variable of Perl or PHP joined with `.` is part of the
  value too, with the strings around it: `$token = 'made' . $x . '...'` hides all of it, and so
  does `$token = q{made}.$x.q{...}`, with no blanks around the `.`, and
  `perl -e "\$token = 'made'.\$x.'...'"` in a shell text, with a backslash before the `$`. The
  variable may stand on a line of its own, with the `.` at the end of a line or at the start of
  the next: `$token = 'made' .`, then `$x .` and `'...'` on the lines after it, hides all three.
  It may be an element of an array or a hash, with `->` or none: `$token = 'made' . $a[0] .
  '...'` hides all of it, as `$x->[0]`, `$h{a}` and `$x['k']` there do. So is a here-document
  joined with `.`: `$token = 'a' . <<'EOT'` hides the lines up to `EOT`. A join after a call,
  a constant, an array such as `@x` or a numbered variable such as `$1`, and a here-document
  joined after an element of an array, are not read with the value, so what follows shows, as
  the [known limits](../../SECURITY.md#known-limits-of-the-shown-command) say. A
  quote-like word given to a name of Perl runs over lines to the mark that closes it, as Perl
  reads it (`$token = q/made`, then `.../` on the next line). A name compared with a value
  (`==`, `!=`, `===`, `!==`, `=~`, `!~`, `eq`, `ne`) loses that value too. In a shell text
  such a string is read whole inside a part in quotes, as the text after `perl -e` is, and in
  the lines of a here-document: `sh -c "perl -e '$token = q/VALUE /; run_old()'"` shows
  `$token = <hidden>; run_old()`, and a string whose quotes a backslash escapes inside double
  quotes is read as the shell hands it on, so `token = f\"made VALUE\"` there is hidden
  whole. A few strings of this kind are read only in part, so the rest of their value shows:
  the [security policy](../../SECURITY.md#known-limits-of-the-shown-command) lists them.
- **The host of an address**, keeping its scheme, port and path, unless it is `localhost`,
  `127.0.0.1`, `::1` or `0.0.0.0`: `https://<hidden>:8443/v1`. A `file://` address with a
  host and no path loses the host the same way (`file://<hidden>`, `file://<hidden>:8000`),
  and a file name typed there with no path before it is read as a host
  (`file://m.gguf` shows `file://<hidden>`). That host ends at any character no host name
  holds, other than the `:` of a port and the `/` of a path, so
  `file://made-up-host,file://other-host` shows `file://<hidden>,file://<hidden>`. A
  `file://` address with a path shows the last part of it: `file://made-up-host/a/m.gguf`
  shows `file://m.gguf`.

### Hidden values that tell two sides apart

The shown command and every hash hide a credential's value whole. Two sides, or one side in two
captures, are still compared on what the value holds besides the credential itself: `plan` and
`run` take two sides that differ there as two sides, with the note
`sides_differ_in_hidden_value`, and `compare` does not pool captures that differ there
(`E_POOL_SIDE_DRIFT`). The note and the refusal name the sides, never the value. Two sides that
differ only in the credential itself are one side (`E_SAME_SIDE`), and captures that differ only
there pool, so a token rotated between two runs does not stop them pooling. The credential
itself is, in this order:

1. an Authorization scheme word and the token after it, when the value starts with one
   (`AUTH_SCHEME_WORDS`): `AUTHORIZATION='Bearer VALUE'`, `--auth='Basic VALUE'`,
   `--token 'Bearer VALUE'`. This rule comes first, so `--token 'Bearer VALUE'` against
   `--token 'Bearer OTHER'` is one side;
2. otherwise the value up to its first blank: `--password 'VALUE tail'` against
   `--password 'VALUE other'` is two sides, and `--password 'VALUE tail'` against
   `--password 'OTHER tail'` is one.

These words count as a difference:

- the words after the credential in a value hidden to the end of its argument, given after `=`
  (`HF_TOKEN=VALUE ./bench-old` against `HF_TOKEN=VALUE ./bench-new`), glued to an option
  (`-eAUTH_TOKEN=Bearer VALUE x`, `mysql -pVALUE x`) or as the next argument
  (`--password 'VALUE x'`, `redis-cli -a 'VALUE x'`);
- the word after an Authorization scheme word that is a credential's whole value, which the
  shown command and every hash hide as a token: `env AUTH=token ./bench-old` against
  `env AUTH=token ./bench-new`, `--auth basic model-a.gguf` against
  `--auth basic model-b.gguf`, and `--token Bearer VALUE` against `--token Bearer OTHER` are
  two sides each, as the word there may be a program, an image or a file as well as a token;
- every word of a client's command glued to its `command` option but the password:
  `--command=AUTH bench VALUE` against `--command=AUTH bench OTHER` is one side, and
  `--command=SET __key__ a` against `--command=SET __key__ b` is two;
- the parts of an address other than its password and the values of its credential-like query
  parameters: its user name (`postgres://alice@db/shop` against `postgres://bob@db/shop`), its
  host, its path, such as the database number of `redis://:VALUE@localhost/0`, and its other
  query parameters. This holds for an address given as the value of a credential-like name or
  option too: `DB_PASSWORD=redis://:VALUE@localhost/0` against `.../1` is two sides, and
  `--auth-url 'http://localhost/v1?token=VALUE&model=a'` against `...&model=b` is two.

A value hidden whole by these forms is compared whole, and a difference in it is no difference:
the value of a credential header (`Authorization: <hidden>`), the value of a credential-like
name in the `env` table of `launch`, a quoted value after a credential-like option inside a
command text (`sh -c "tool --password 'VALUE x'"`), and a value whose first word is no address,
such as `--token=VALUE&model=a`, where the `&model=a` is read as part of the token.

### Texts read word by word

Some arguments hold a command or a list of words. Their words are read one by one, each through
every rule on this page, so a hidden value ends at its first unquoted blank and the program
after it stays shown:

- **A command text.** The text after `-c` (`sh -c`, `bash -lc`, `python -c`); the text a shell
  (`sh`, `bash`, `dash`, `zsh`, `ksh`, `mksh`, `ash`, `yash` or `fish`: `SHELLS`) runs after a
  group of options that holds `c` anywhere, also with other options or `--` after it
  (`sh -ce`, `bash -xc`, `sh -c -- TEXT`, `bash -c -e TEXT`); the remote command of `ssh`,
  after its host; the commands of `hyperfine` and `watch`, of `parallel` up to `:::`, `:::+`,
  `::::` or `::::+`, and of `tmux` after `new`, `new-session`, `new-window`, `neww`,
  `split-window`, `splitw`, `respawn-window`, `respawnw`, `respawn-pane` or `respawnp`
  (`COMMAND_TEXT_RUNNERS`); and the value of `gcloud ... --command`, of `env -S` or
  `--split-string`, of `-s`, `--setup`, `-p`, `--prepare`, `-C`, `--conclude`, `-c`,
  `--cleanup` or `--reference` of `hyperfine`, also in a group after its `-N`, `-i` or `-S`
  (`-NpTEXT`) and wherever `hyperfine` starts a command in the words of `ssh`, `watch` or
  `parallel`, which a shell runs once they are joined: first, or after a separator, after the
  assignments that lead it, after `env`, `sshpass`, `taskset`, `numactl`, `chrt`, `stdbuf`,
  `ionice`, `time`, `nice`, `nohup`, `timeout` or `sudo` read as below, or after the host of a
  nested `ssh`
  (`ssh made-up-host taskset -c 0 hyperfine --setup=TEXT ./bench-old`), and of `-c` or `--command`
  of `su`, `runuser`, `flock`, `script` and `fish`
  (`TEXT_OPTIONS`), given as the next argument or glued to the option. So `ssh made-up-host 'API_KEY=VALUE ./bench-old'`
  shows `ssh made-up-host 'API_KEY=<hidden> ./bench-old'`, and so does a command text inside
  another one. An option of `parallel`, or of `watch` but for `-n` and `--interval`, is read as
  one word, so the word after an option given its value in the next word (`parallel -j 2`) is
  read as the command, as the
  [known limits](../../SECURITY.md#known-limits-of-the-shown-command) say; glue such an
  option to its value (`parallel -j2`). A text glued to its option is read as the same text given as the next
  argument, so its first word names a client too:
  `gcloud compute ssh made-up-vm '--command=mysql -pVALUE'` shows
  `gcloud compute ssh made-up-vm '--command=mysql -p<hidden>'`,
  `hyperfine '--setup=redis-cli -a VALUE FLUSHALL' ./bench-old` shows
  `hyperfine '--setup=redis-cli -a <hidden> FLUSHALL' ./bench-old`, and
  `env -Sredis-cli -a VALUE` shows `env -Sredis-cli -a '<hidden>'`. So is the text glued to
  `--command=`, `--cmd=`, `--exec=` or `--run=` of a program that is none of these and no client
  with options of its own (`made-up-tool`), read as that text given as the next argument is:
  `made-up-tool '--command=redis-cli -a VALUE PING'` shows
  `made-up-tool '--command=redis-cli -a <hidden> PING'`. The parser of `hyperfine`
  also takes an `=` between a short option and its glued text off the text
  ([clap 4.5.20](https://github.com/clap-rs/clap/blob/v4.5.20/clap_builder/src/parser/parser.rs),
  which hyperfine 1.19.0 is built with), so `hyperfine '-s=redis-cli -a VALUE FLUSHALL' ./bench-old`
  shows `hyperfine '-s=redis-cli -a <hidden> FLUSHALL' ./bench-old`. From
  [hyperfine 2.0.0](https://github.com/sharkdp/hyperfine/blob/v2.0.0/src/cli.rs) on, `-S`
  takes no value, so `-SsTEXT` is `-S` and `-s TEXT`. These programs are read
  where a command starts: its first word, the first word
  of the workload after `--`, the word after a separator or a line break, the word after a
  reserved word of a shell that a command follows (`{`, `!`, `if`, `then`, `else`, `elif`,
  `while`, `until`, `do`, and the body of a function), after the assignments that lead a
  command, and the command that `env` or `sshpass` runs. So is the
  command that `taskset`, `numactl`, `chrt`, `stdbuf`, `ionice`, `time`, `nice`, `nohup`,
  `timeout` or `sudo` runs, after the options of each, the assignments of `sudo`, and the mask
  of `taskset`, the priority of `chrt` or the duration of `timeout`, read with the options
  their own manuals give that take a value
  ([taskset(1)](https://github.com/util-linux/util-linux/blob/v2.42/schedutils/taskset.1.adoc),
  [chrt(1)](https://github.com/util-linux/util-linux/blob/v2.42/schedutils/chrt.1.adoc) and
  [ionice(1)](https://github.com/util-linux/util-linux/blob/v2.42/schedutils/ionice.1.adoc) of
  util-linux 2.42, [numactl(8)](https://github.com/numactl/numactl/blob/v2.0.19/numactl.8) of
  numactl 2.0.19, [stdbuf(1)](https://man7.org/linux/man-pages/man1/stdbuf.1.html),
  [nice(1)](https://man7.org/linux/man-pages/man1/nice.1.html),
  [nohup(1)](https://man7.org/linux/man-pages/man1/nohup.1.html) and
  [timeout(1)](https://man7.org/linux/man-pages/man1/timeout.1.html) of GNU coreutils 9.11,
  [sudo(8)](https://github.com/sudo-project/sudo/blob/v1.9.17p2/docs/sudo.mdoc.in) of sudo
  1.9.17p2, and [time](https://www.gnu.org/software/time/manual/time.html) of GNU time 1.9
  with the `-p` of a shell's own `time`): `taskset -c 0-3 ssh made-up-host 'API_KEY=VALUE ./bench-old'` shows
  `taskset -c 0-3 ssh made-up-host 'API_KEY=<hidden> ./bench-old'`, and
  `timeout -s KILL 30 ssh made-up-host 'API_KEY=VALUE ./bench-old'` shows
  `timeout -s KILL 30 ssh made-up-host 'API_KEY=<hidden> ./bench-old'`. After any other
  program, such as `setsid` or `doas`, the text of `ssh`, `hyperfine`, `watch`,
  `parallel` or `tmux` is read as any argument is, so a credential's value there runs to the
  end of the text: `setsid ssh made-up-host 'API_KEY=VALUE ./bench-old'` shows
  `setsid ssh made-up-host 'API_KEY=<hidden>'`. The value of one of their own options, such as
  `ssh -o` or `tmux -e`, is no command text and keeps the rule for a value. In each of these
  texts but the one after `-c` of a program that is no shell (`python -c`), the words end
  where a shell's words end: a value given with `=` ends where its shell word ends, so `=` or
  `==` followed by a blank gives the empty value, and
  `sh -c 'tool API_KEY= && ./bench-old'` shows `sh -c 'tool API_KEY=<hidden> && ./bench-old'`.
  A value that ends in `=` is still hidden whole. The lines of a here-document there
  (`<<EOF` up to `EOF`) are read as a program's text, where a value after `=` and a blank is
  the name's value and a string that a mark of its own opens is hidden whole:
  `sh -c "python3 <<'END'` and the line `token = f'VALUE'` show `token = <hidden>`. A word that a runner passes to its program as one argument, as each word
  of the command of `watch -x` is, is none of these texts and is read as any argument is.
- **The value of an ordinary name.** An argument that gives a value to a name that is no
  credential, a variable (`MADE_UP_FLAGS=`, also with a `-` or a `.` in the name) or an option
  joined by `=`, has its value read word by word:
  `env 'MADE_UP_FLAGS=--api-key=VALUE --threads 8' mytool` shows
  `env 'MADE_UP_FLAGS=--api-key=<hidden> --threads 8' mytool`, as do `docker run -e`,
  `--env=` and `ssh -o SetEnv=`. Every word keeps every rule, so a random-looking word in it is
  hidden by its shape. A credential name after an ordinary one hides the rest of the value:
  `SetEnv=DB_PASSWORD=<hidden>`. A value in quotes is read the same way, and so is a word
  quoted whole that gives a name its value, as a shell text writes them:
  `sh -c 'env MADE_UP_FLAGS="--api-key VALUE --threads 8" mytool'` shows
  `sh -c 'env MADE_UP_FLAGS="--api-key <hidden> --threads 8" mytool'`.
- **A word in quoted parts.** In a shell text a word written in parts, quoted or with escapes,
  such as `--token" VALUE"`, gives its program one argument with the quotes taken off,
  `--token VALUE`, and is read as the text of that argument. A text that a second shell runs, as
  the remote command of `ssh` or the text after `-c` of a shell in a shell text, splits that
  argument into words, so it is read as a shell text. When the reading hides a value, the word
  is shown quoted whole: `sh -c 'mytool --token" VALUE" --threads 8'` shows
  `sh -c "mytool '--token <hidden>' --threads 8"`, and
  `sh -c 'ssh made-up-host ./bench --token" VALUE"'` shows
  `sh -c "ssh made-up-host ./bench '--token <hidden>'"`. Inside a word in single quotes such a
  word is shown in double quotes, and the other way round, so the quotes around it still hold:
  `sh -c "ssh made-up-host './bench --token\ VALUE'"` shows
  `sh -c "ssh made-up-host './bench \"--token <hidden>\"'"`. Inside both kinds of quotes its
  blanks are escaped instead (`--token\ <hidden>`). A text in double quotes that the next shell
  reads, the remote command of `ssh` or the text after `-c` of a shell in a shell text, is read
  as that shell gets it, with `\"` and `\\` taken out: in
  `sh -c 'ssh made-up-host "./bench --token\" VALUE\""'` the remote command is shown as
  `"./bench '--token <hidden>'"`, and an operator between such escaped quotes is part of the
  value, so `\"password=a;VALUE\"` there hides all of `a;VALUE`.

### Password options of benchmark clients

These options take a password though their names do not say so. A client is found by its
program word, also when a path names it (`/usr/local/bin/redis-benchmark`), when `env`,
`sudo`, `docker exec` or a shell runs it, and after a command separator (`;`, `&`, `|`, a
bracket or a backquote). Its options hold up to the end of its command. In a shell text an
operator outside quotes ends the command, and one in quotes does not:
`mysql -e 'select 1; select 2' -pVALUE` shows `mysql -e 'select 1; select 2' '-p<hidden>'`.
In an argument list that no shell reads, no word ends the command, not even a word that is an
operator on its own: `redis-cli -d ';' -a VALUE` shows `redis-cli -d ';' -a '<hidden>'`. A
redirection is no word of the client's command, as a shell takes it out before the client runs,
and in an argument list it was most likely meant for a shell, so it is passed over there too:
`sh -c 'redis-cli -a 2>&1 VALUE PING'` shows `sh -c 'redis-cli -a 2>&1 <hidden> PING'`,
`sh -c 'redis-benchmark -n 1000 >|out -a VALUE'` shows `sh -c 'redis-benchmark -n 1000 >|out -a <hidden>'`
and `redis-cli -n 1 '>' out AUTH VALUE` shows `redis-cli -n 1 '>' out AUTH '<hidden>'`. Outside a
shell text, a redirection with a file glued to it that stands where a password option takes its
value may be the value as typed, and it is hidden: `redis-cli -a '>VALUE' PING` shows
`redis-cli -a '<hidden>' PING`. One that stands alone or gives one descriptor to another, and
the file after one, may be the value as typed too, while a shell would give the option the word
after them, so both are hidden there: `redis-cli -a '2>&1' VALUE PING` shows
`redis-cli -a '<hidden>' '<hidden>' PING`. An option given as the file of a redirection is read
as the option, as the text holds it either way: `sh -c 'redis-cli > -a VALUE'` shows
`sh -c 'redis-cli > -a <hidden>'`; so is a rule of `ACL SETUSER` that gives a password
(`>VALUE`), wherever it stands. In an argument list, a word that looks like a redirection where a
Redis command takes a user or setting name is that name, as the client gets it, and the password
of either reading is hidden: `redis-cli ACL SETUSER '>NAME' '>VALUE'` shows
`redis-cli ACL SETUSER '>NAME' '><hidden>'`, `redis-cli HELLO 3 AUTH '>NAME' VALUE` shows
`redis-cli HELLO 3 AUTH '>NAME' '<hidden>'`, and `redis-cli CONFIG SET '<NAME' 1 requirepass VALUE`
shows `redis-cli CONFIG SET '<NAME' 1 requirepass '<hidden>'`; after such a user name of `HELLO`
the word after the password is hidden as well. A
command substitution in a shell text (`$(...)`, a text in backquotes, `<(...)` or `>(...)`) is
one word of the command it stands in, and its own text is a command of its own, read with the
client it names: `sh -c './bench --label $(redis-cli -a VALUE get k) -n 5'` shows
`sh -c './bench --label $(redis-cli -a <hidden> get k) -n 5'`, and the client before a
substitution keeps its options after it: `sh -c 'redis-benchmark -n $(nproc) -a VALUE'` shows
`sh -c 'redis-benchmark -n $(nproc) -a <hidden>'`. Substitutions inside substitutions are read
eight deep, and the text of a deeper one is hidden whole. The words of an `eval` are read as
the one shell text it runs, with their quotes taken off and their escapes read, when one of
them is quoted or escaped: `sh -c "eval memtier_benchmark --command \'AUTH VALUE\'"` shows
`sh -c 'eval "memtier_benchmark --command '"'"'AUTH <hidden>'"'"'"'`. A credential given its
value at the start of that text loses only its value, as it does outside an `eval`, so the program
after it stays: `sh -c 'eval "PGPASSWORD=VALUE psql -h db.example"'` shows
`sh -c 'eval "PGPASSWORD=<hidden> psql -h db.example"'`, and so does a value written in
escaped quotes inside the text, as `'PGPASSWORD='\''VALUE'\'' psql'` writes it. An `eval` after
one of the reserved words that a command follows, as in `{ eval ...; }` or
`if true; then eval ...; fi`, after a line continuation, or in a command substitution, a
process substitution or a subshell, is read the same way:
`sh -c 'x=$(eval "PGPASSWORD=VALUE psql -h db.example")'` shows
`sh -c 'x=$(eval "PGPASSWORD=<hidden> psql -h db.example")'`. A command substitution inside
double quotes is read as the shell text it is too, so a value in escaped double quotes there
is hidden and the program after it stays:
`sh -c 'x="$(eval "PGPASSWORD=\"VALUE\" psql -h db.example")"'` shows
`sh -c 'x="$(eval '"'"'PGPASSWORD=<hidden> psql -h db.example'"'"')"'`. A text in
backquotes is read as the shell runs it, with the backslash taken off before a backslash, a
backquote or a `$`, and in backquotes inside double quotes before a `"` too:
``sh -c 'x="`eval "PGPASSWORD=\\"VALUE\\" psql -h db.example"`"'`` shows
``sh -c 'x="`eval '"'"'PGPASSWORD=<hidden> psql -h db.example'"'"'`"'``. The text an `eval`
runs is read with the code of its programs, as it would be outside an `eval`:
`sh -c "eval python3 -c \\\"token = \\'VALUE\\'\\\""` shows
`sh -c 'eval "python3 -c \"token = '"'"'<hidden>'"'"'\""'`. A text typed as one
word in one kind of quotes is shown in them, after the `--` of `eval` if it has one. The text
of an `eval` is one more of those eight levels, as a substitution is.

A client named only in a side's spec is found too. The shared workload is read after the words
each command side runs before `{workload}`, from each `--side NAME=cmd:SPEC` and from the `cmd`
of each side in the config, and a word of it is hidden when the reading after any side hides
it. So with `--side 'old=cmd:./build-old/redis-benchmark {workload}'`, the workload
`-- -a VALUE -n 1000` shows `-- -a '<hidden>' -n 1000`, and `config_sha256` reads the workload of
the config file the same way. So does the `argv_sha256` of every command side, and so its
fingerprint: next to that side, `--side 'new=cmd:./bench {workload}'` hashes `-a <hidden>` too,
and two runs that differ in the password alone pool. The workload starts a command of its own
after a side's words before `{workload}`, unless their last word waits for it: an option's
value, a shell's options, the operands of `ssh` or another runner of command texts, or the
command `env` runs. So `-- ssh made-up-host 'API_KEY=VALUE;./bench-new'` reads its text the same
after `timeout 60 {workload}`, `./runner {workload}` or `redis-benchmark {workload}` as alone,
and `./bench-new` tells it from `./bench-old`.

A shell text that hands its arguments on is read with them in place. In
`sh -c TEXT NAME ARG...`, each command of `TEXT` that uses `"$@"`, `$*`, `"$1"` or `${2}` is
read with the arguments where it uses them, and so is a shell text such a command runs with
them. So a side with `cmd = ["sh", "-c", "redis-benchmark \"$@\"", "_", "{workload}"]` shows the
same workload as `-- -a '<hidden>' -n 1000`, and its fingerprint is the same for two passwords. A
parameter in single quotes or after a backslash is text and is not read so. A command the text
repeats is read once, and the reads stop after as many characters as the command holds and
65536 more: an argument a command past that would take is hidden. So two workloads that differ
only in such arguments, such as two long lists of file names that the text hands to two
commands, show and hash alike: past that bound the hash does not tell them apart.

An image side that names no `entrypoint` and no `args` gives the shared workload to its image's
own entrypoint, and the workload is read after that entrypoint as the engine reports it. So with
an image whose entrypoint is `memtier_benchmark`, the workload `-- -s HOST -a VALUE -n 1000`
shows `-- -s HOST -a '<hidden>' -n 1000`, and `config_sha256` is the same for two passwords. An
image with no entrypoint runs the workload's first word, and the workload is read as it stands.
When the entrypoint names no client of the table below and the workload starts with an option,
the workload is read after the first word of the image's command too: a wrapper script such as
`docker-entrypoint.sh` with the command `memtier_benchmark` hides `-a VALUE` the same way. A
client that a wrapper script starts in any other way is not found; set `sides.NAME.entrypoint`
to the client, so that the workload is read after it. When the engine's details of the image do
not say what its entrypoint is, the run is refused with
[`E_ENTRYPOINT_UNREADABLE`](exit-codes.md#e_entrypoint_unreadable) before anything starts.

| Program | Option | Shown as |
|---|---|---|
| `redis-benchmark`, `redis-cli`, `valkey-benchmark`, `valkey-cli` | `-a VALUE`, `-aVALUE` | `-a <hidden>` |
| `memtier_benchmark` | `-a VALUE`, `-aVALUE`, `--authenticate VALUE`, `--authenticate=VALUE` | `--authenticate <hidden>` |
| `memtier_benchmark` | `-a user:VALUE`, `-auser:VALUE`, `--authenticate user:VALUE` | `--authenticate user:<hidden>` |
| `mysql`, `mysqlslap`, `mysqladmin`, `mariadb`, `mariadb-slap`, `mariadb-admin` | `-pVALUE` | `-p<hidden>` |
| `sshpass` | `-p VALUE`, `-pVALUE` | `-p <hidden>` |
| `ab` | `-A user:VALUE`, `-P user:VALUE` | `-A user:<hidden>` |
| `vllm`, `vllm.entrypoints.openai.api_server` | `--api-key VALUE VALUE`, `--api_key VALUE VALUE` | `--api-key <hidden> <hidden>` |
| `curl` and any other program but a Redis or Valkey server | `-u`, `--user`, `-U`, `--proxy-user` with `user:VALUE` | `-u user:<hidden>` |
| `redis-server`, `redis-sentinel`, `valkey-server`, `valkey-sentinel` | `--sentinel auth-pass master VALUE`, `--sentinel sentinel-pass VALUE` | `--sentinel auth-pass master <hidden>` |
| `redis-server`, `redis-sentinel`, `valkey-server`, `valkey-sentinel` | `--user name on >VALUE`, `<VALUE`, `#VALUE`, `!VALUE` | `--user name on ><hidden>` |

A Redis or Valkey server reads each `--NAME` of its command line and the words after it as a
line of its config file, and `--sentinel` starts a line of a Sentinel's config. The passwords a
server takes by a name that says so are hidden by that name (`--requirepass`, `--masterauth`,
`--primaryauth`, and `MASTERAUTH=VALUE` in the environment). After `--sentinel`, the value of
`auth-pass` follows the master's name, which is shown, and `sentinel-pass` gives the Sentinel's
own password; `auth-user` and `sentinel-user` give user names, which are shown. So
`redis-sentinel sentinel.conf --sentinel auth-user master app --sentinel auth-pass master VALUE`
shows `--sentinel auth-user master app --sentinel auth-pass master <hidden>`.
`--user` starts a `user` line, as in the server's config: the next word is the user's name,
which is shown, and each word after it up to the next `--NAME` is one of that user's rules,
read as a rule of `ACL SETUSER` is. A rule that gives a password or its hash (`>VALUE`,
`<VALUE`, `#VALUE`, `!VALUE`) keeps its first character, so
`redis-server --user app on '>VALUE' '~*' +@all --port 7000` shows
`--user app on '><hidden>' '~*' +@all --port 7000`. A `--NAME` right after `--user` is read
as the next option and not as a name, so `redis-server --user --requirepass VALUE` shows
`--user --requirepass <hidden>`.

The OpenAI-compatible server of vLLM, started as `vllm serve` or as
`python -m vllm.entrypoints.openai.api_server`, takes one API key or more after `--api-key`
and reads `--api_key` as the same option, as its parser reads them in
[vLLM 0.33.0](https://github.com/vllm-project/vllm/tree/v0.33.0). Each word after the option
is hidden, up to the next word that starts with `-`, a shell operator or the end of the
command: `vllm serve org/model-a --api-key VALUE VALUE --port 8000` shows
`vllm serve org/model-a --api-key '<hidden>' '<hidden>' --port 8000`. A model written after the
keys is one more key to the server and is hidden with them. A key glued after `=` is the
option's only one, so `vllm serve --api-key=VALUE org/model-a` shows
`vllm serve '--api-key=<hidden>' org/model-a`, and after any other program `--api-key` hides
one word: `./made-up-tool --api-key VALUE made-up-out.json` shows
`./made-up-tool --api-key '<hidden>' made-up-out.json`.

The `mysql` clients hide only the joined form: with a space, `-p` asks for the password and the
next word is a database name, which is shown (`mysql -p shop`). The options of `sshpass` end at
the command it runs, so `sshpass -p VALUE ssh -p 2222 HOST` shows
`sshpass -p '<hidden>' ssh -p 2222 HOST` and keeps the port `2222`. A value glued to one of these
options is hidden to the end of its argument, spaces included: `mysql '-pa b' shop` shows
`mysql '-p<hidden>' shop`. It ends there, whatever words it holds, and the next argument is read
as the client's own: `redis-cli -aVALUE PING` shows `redis-cli '-a<hidden>' PING`, and
`sshpass -pVALUE ssh HOST` keeps `ssh`. The table gives each form without the quotes that the
shown command puts around a word that holds `<hidden>`, as a shell reads it:
`redis-benchmark -a VALUE` shows `redis-benchmark -a '<hidden>'`, and `redis-benchmark -aVALUE`
shows `redis-benchmark '-a<hidden>'`.

A client's options also read the value of an ordinary name given before a later word of the
same command that names the client, as `env`, `docker run -e` and the assignments that lead a
shell command give one, shown and hashed alike:
`env 'MADE_UP_FLAGS=-a VALUE -n 8' redis-benchmark` shows
`env 'MADE_UP_FLAGS=-a <hidden> -n 8' redis-benchmark`, and
`sh -c 'REDIS_ARGS="-a VALUE" redis-benchmark $REDIS_ARGS'` shows
`sh -c 'REDIS_ARGS="-a <hidden>" redis-benchmark $REDIS_ARGS'`. A password glued to its option
there keeps the option: `MADE_UP_FLAGS=-pVALUE mysql` shows `MADE_UP_FLAGS=-p<hidden> mysql`.
A value before a program that is no client, or before a client of another command, after a
separator or a line break, is read as it stands. So is a variable that one command sets and a
later command, a script or a shell text reads, which the security policy lists as a known
limit.

`memtier_benchmark -a` and `--authenticate` take a password, or a user and a password written
`user:password`, split at the first `:`, as
[`memtier_benchmark` 2.1.4](https://github.com/RedisLabs/memtier_benchmark/blob/2.1.4/protocol.cpp)
reads them. The user is shown and the password hidden (`--authenticate app:<hidden>`); a value
that starts with `:` is a password alone and is hidden whole. The value after
`--authenticate=` is hidden whole, as the value of any option whose name says credential.

### Passwords in the commands of Redis and Valkey

The command a Redis or Valkey client sends is read as the command of the data store: the
command of `redis-cli`, `valkey-cli`, `redis-benchmark` or `valkey-benchmark`, its first word
that is no option and no value of an option, also when it is one quoted word
(`redis-benchmark -n 10 'AUTH <hidden>'`), and the text of `memtier_benchmark --command`,
given as the next argument or after `=`. A command and its words are read in any case:
`auth user password`, `Auth user password` and `AUTH user password` each show the user and hide
the password, and so does every row below written in lower case
(`config set requirepass <hidden>`). Each password is hidden whole and each user name is shown:

| Command | Shown as |
|---|---|
| `AUTH password` | `AUTH <hidden>` |
| `AUTH user password` | `AUTH user <hidden>` |
| `HELLO 3 AUTH user password` | `HELLO 3 AUTH user <hidden>` |
| `HELLO 3 SETNAME name AUTH user password` | `HELLO 3 SETNAME name AUTH user <hidden>` |
| `MIGRATE host port key db timeout AUTH password` | `MIGRATE host port key db timeout AUTH <hidden>` |
| `MIGRATE host port key db timeout AUTH2 user password` | `MIGRATE host port key db timeout AUTH2 user <hidden>` |
| `MIGRATE host port key db timeout COPY REPLACE AUTH password` | `MIGRATE host port key db timeout COPY REPLACE AUTH <hidden>` |
| `MIGRATE host port '' db timeout AUTH password KEYS key key` | `MIGRATE host port '' db timeout AUTH <hidden> KEYS key key` |
| `CONFIG SET masterauth password`, `CONFIG SET requirepass password` | `CONFIG SET masterauth <hidden>` |
| `CONFIG SET masteruser user masterauth password` | `CONFIG SET masteruser user masterauth <hidden>` |
| `CONFIG SET 'requirepass password'` | `CONFIG SET 'requirepass <hidden>'` |
| `ACL SETUSER user on >password`, `<password`, `#hash`, `!hash` | `ACL SETUSER user on ><hidden>` |
| `ACL SETUSER user 'on >password ~* +@all'` | `ACL SETUSER user 'on ><hidden>'` |
| `ACL SETUSER user reset on >password >password ~* +@all` | `ACL SETUSER user reset on ><hidden> ><hidden> ~* +@all` |
| `SENTINEL SET master auth-pass password` | `SENTINEL SET master auth-pass <hidden>` |
| `SENTINEL CONFIG SET sentinel-user user sentinel-pass password` | `SENTINEL CONFIG SET sentinel-user user sentinel-pass <hidden>` |
| `--user user --pass password` | `--user user --pass <hidden>` |

`AUTH` of `HELLO` is read wherever it stands after `HELLO`, before or after `SETNAME`. `AUTH`
and `AUTH2` of `MIGRATE` are read after its five fixed arguments, after `COPY` and `REPLACE` too,
and the words after the password are shown (`KEYS key key`). `ACL SETUSER` hides every rule that
gives a password or its hash, however many it has. A password may hold blanks, so all of an
argument after its first rule that gives one is hidden, blanks included: `'>made up'` and
`'> made up'` show `'><hidden>'`, and the rules before it in the same argument are shown.
A shell takes off a backslash before a rule's first character, so a rule typed so in a shell
text is read as the shell reads it: `sh -c 'redis-cli ACL SETUSER app on \>VALUE'` shows
`sh -c 'redis-cli ACL SETUSER app on \><hidden>'`. So is a rule in the words that `ssh` hands
to a shell on the other machine, or that `watch` or `parallel` hands to a shell:
`ssh made-up-host redis-cli ACL SETUSER app on '\>VALUE'` shows
`ssh made-up-host redis-cli ACL SETUSER app on '\><hidden>'`. So is a rule after a program in
front of `ssh`, `watch` or `parallel` (`timeout 5 ssh ...`), in a shell text that one of their
words holds (`ssh made-up-host sh -c '...'`), and after `hyperfine -N`, which splits its command
into words with no shell and takes the backslash off too. No rule starts with a backslash, so a
rule typed with one loses its value wherever it stands, also with no shell between, as after
`watch -x` or `parallel -q`, where the client gets the backslash and refuses the rule. An
ordinary word with a backslash keeps it (`redis-cli SET k '\>v'`), and so does a user name.

`CONFIG SET` reads its words as names and values in turn, so each setting after a password keeps
its value (`CONFIG SET requirepass <hidden> maxmemory 100mb`); so do `SENTINEL SET` after the
master's name and `SENTINEL CONFIG SET`, where `auth-user`, `sentinel-user` and `quorum` keep
their values. In a shell text, a word the shell may make no word or several of (`$NAME`,
`$(...)`, a text in backquotes, `"$@"`) leaves the turn unknown, so after it a credential
setting's name hides the next word wherever it stands, and `AUTH` and `AUTH2` of `MIGRATE` are
read after any count of words:
`sh -c 'redis-cli CONFIG SET $(echo a b) requirepass VALUE'` shows
`sh -c 'redis-cli CONFIG SET $(echo a b) requirepass <hidden>'`. `CONFIG SET masteruser NAME` keeps
its user name, the other rules of `ACL SETUSER` are shown (`nopass`, `~*`, `+@all`) in an
argument of their own or before the password in one argument, and a
`SET` of a key keeps the key and its value
(`memtier_benchmark --command 'set __key__ __data__ EX 60'`). After `AUTH`, a word that
another word of the same command follows, past any redirection such as `>out.log`, is the user
name; a separator, a line break, a comment (`# log in`) or the end of the command ends it. A word
followed by an option (`--raw`, `-e`), or by a redirection or a comment given as an argument
(`'>out.log'`, `'#'`), is hidden as the password, since the client reads its options before
the command and passes that next word on as the password; the next word is hidden too unless
it is a long option, so `redis-cli AUTH VALUE --raw` shows `redis-cli AUTH <hidden> --raw` and
`redis-cli AUTH VALUE '#' log in` shows `redis-cli AUTH <hidden> <hidden> log in`. `redis-cli --askpass` and
`--cluster-from-askpass` ask for the password and take no value, and `--show-pushes`, `-X`,
`--lru-test`, `--cursor` and `--top` take one, so the command starts after that value. So the
option parsing of [`redis-cli` 8.0.0](https://github.com/redis/redis/blob/8.0.0/src/redis-cli.c)
reads them; [`valkey-cli` 8.1.1](https://github.com/valkey-io/valkey/blob/8.1.1/src/valkey-cli.c)
reads the same options but `--cursor` and `--top`, which it refuses. A command
the client reads from its input, as in
`echo 'AUTH password' | redis-cli`, is an argument of the program that writes it and is not read
as a Redis command; give the password with `-a`, `--pass` or through `launch.env_pass`.

### Long random-looking values

A value that nothing names is hidden by its shape when it looks like the output of a token or
key generator: a plain argument, the value of an option, a segment of a path, and a path segment
or query value of an address (`http://localhost:8000/v1/files/<hidden>/raw?part=<hidden>`). An
absolute path that holds one, and a path that starts with `./`, `../` or `~/`, is hidden whole,
so no part of the value shows as the last part of the path (`../data/<key>/out.json` shows
`..<hidden>.json`); so is the path of an address whose host is empty (`sqlite:///...`) and the host and
path of a `file://` address, which are cut the same way. Here and below, `<key>` stands for a
made-up key of letters and digits that looks random by itself, such as
`EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw`.

The rule reads each run of letters, digits, `+`, `/`, `_` and `-`, with up to two `=` of padding
at its end, which it leaves out. A run that holds a `/` and a `+` or `=` padding, as base64 is
written, and does not start with `/`, is judged whole first: when it looks random, it is hidden
whole, wherever it stands (`--hmac <hidden>`, `--hmac=<hidden>`, `BLOB=<hidden>`), so no part of
it between two `/` shows. A run with a `/` and neither a `+` nor padding is judged whole between
the words of a path at its ends: a number, one or two small letters, a small letter and digits,
three or more small letters with a vowel among them, or such pieces joined by `-`, `_` or `+`
(`data`, `v1`, `run_01`). When what lies between them holds a `/` and looks random, it is hidden
whole and the words around it stay shown: `data/<hidden>/out.json`,
`http://localhost:8000/v1/files/<hidden>/raw`. When what lies between them is shorter than 32
characters, it is read with up to two short words of a path on each side of it, which a key
holds at an end by chance: words with no run of three small letters and no `-` or `_`, such as
`8`, `au`, `j0`, `7b` or `p+em2`. When they make 32 characters or more and what lies between
them passes tests 2 to 5 below, it is hidden with them:
`data/au/EXAMPLETailFakezQ9zQx9XyTAILRea/p+em2/out.json` shows `data/<hidden>/out.json`.
When what lies between them is not hidden so, it is also read with
up to two of its longer words of a path (three small letters or more, or a `-` or `_`) at each
of its ends left out, with the parts up to them, then with the parts of three small letters or
more at its ends left out, and then with those parts and the words of a path before or between
them left out: a folder that is no word of a path, such as `srv` or `nfs`, may stand before a
key, and `srv/data/EXAMPLETailFakezQ9/zQx9XyTAILRealUP/out.json` shows
`srv/data/<hidden>/out.json`. The first of these readings that hides a key is the one used.
When no word of a path comes before it, the whole run is hidden (`client <hidden>`). A folder
such as `srv` or `nfs` before a key that looks random by itself is hidden with the key:
`srv/data/<key>/out.json` shows `<hidden>.json`, `srv/nfs/<key>/x.bin` shows `<hidden>.bin`
and `v1/srv/nfs/<key>/x.bin` shows `v1/<hidden>/x.bin`. A run stays shown when each part
between two `/` reads as a
name: it does not look random, and it is hexadecimal or each piece of it between `-` and `_` is
written in CamelCase or as tags, or fails one of the tests below; and when the run, or what lies
between its words of a path, looks random as a whole, each part there also holds a `-` or `_`,
or is written in CamelCase, as small letters and digits or as tags
(`made-up/Model-3B-Instruct-FP8`, `data/run_01/out.json`). Tags are letters and digits, under
32 characters, in which each run of small letters is `x`, `v` or `p` alone, or holds one of
the vowels `a`, `e`, `i`, `o` and `u` and follows a capital (`TP8PP2DP4`, `BS256xSeq4096`,
`Q100x8`); a word of three small letters or more with such a vowel may open them when each later
run of small letters is `x`, `v` or `p` (`madeLLMv0p6`).
So `results/Quill-3.1-70B-Chat/TP8PP2DP4/BS256xSeq4096/Q100x8/summary.json` shows whole. Any
other run is judged part by part: each part between two `/`, then
each part of letters and digits, then, when nothing in it is hidden and it holds a `/`, the whole
run. A run with a `+` or `=` padding that does not start with `/` is hidden whole when any part
of it is, so no part of a base64 value shows beside a hidden one. In that last
judgement a part made only of digits, as a number argument is written, and a group name of small
letters and digits that holds a `_` or `-` are left out of the share of words in test 5, each with
its `/`; every other test reads the whole run. So `BM_Crc32BatchNormMapTensorPut/4096/4` and
`tree_parse/MapMaxHTTP2PopCopyCopy/16/64` stay shown as `BM_Crc32BatchNormMapTensorPut/64` does,
while a random run with a short part beside its long one is hidden whole. A value is
random-looking when:

1. it is at least 32 characters long (`RANDOM_MIN_LENGTH`), and is not made of digits only;
2. it holds both capitals and small letters;
3. its kind of character (capital, small letter, digit) changes between two neighbours at least
   once in every 3 characters (`RANDOM_CHANGE_EVERY`): the number of changes times 3 is at
   least the length;
4. a capital is followed by another capital or by a digit at least 1 time
   (`RANDOM_MIN_CAPITAL_PAIRS`);
5. less than 60 percent of its characters (`RANDOM_WORDS_SHOWN_PERCENT`) are in words, a word
   being a capital followed by 3 or more small letters (`RANDOM_WORD_SMALL_LETTERS`), as in
   `Tensor`, or by 2 small letters one of which is a vowel, `a`, `e`, `i`, `o`, `u` or `y`
   (`RANDOM_WORD_VOWELS`), as in `Get`. A name in CamelCase, such as
   `MadeUpModelForCausalLMWithValueHead` or `BM_LruCacheGetPutMixedKeyLen16ValLen64`, is mostly
   words and is shown.

Where a random-looking value stands changes only how much around it is hidden:

- glued to an option of one letter, it keeps the letter: `-kVALUE` shows as `-k<hidden>`;
- a run that holds percent escapes, such as `%2F` in a query value, is judged as the text the
  escapes stand for, whole and part by part as above, and is hidden whole when that text or any
  part of it looks random;
- a run that holds `+/`, as base64 often does, is hidden whole when any part of it looks random,
  so no part of it shows as the last part of a path;
- in an address, the port and the words of the path stand in one run with a base64 value that
  holds a `+` or padding, and are hidden with it: `http://127.0.0.1:<hidden>`;
- a run with a `/` and neither a `+` nor padding keeps the words of a path at its ends and is
  hidden between them, as a path or an address is written: `data/<hidden>/out.json` keeps its
  words, and a base64 value written without `+` or padding, whose first part is no word of a
  path, is hidden whole (`client <hidden>`);
- a UUID is an id and stays shown, also after a word and a `-`, as a device id is written.

Hexadecimal, made only of digits and the letters `a` to `f` in either case, has a rule of its
own, since a key is often written in it (`openssl rand -hex 16` prints 32 characters):

- under 32 characters it is shown, such as a short commit id or image id of 7 to 12
  characters;
- exactly 40 characters is a commit id and is shown (`COMMIT_ID_LENGTH`) on its own, and between
  two `/` right after one of the folders `archive`, `blob`, `commit`, `commits`, `resolve`,
  `snapshots` or `tree` (`COMMIT_ID_FOLDERS`), as a code host or a model hub writes a path pinned
  to a commit (`org/repo/commit/<id>`, `org/Model-3B/resolve/<id>/config.json`); anywhere else
  between two `/`, as a token in the path of a hook's address is written, it is hidden as other
  hexadecimal is (`http://localhost:8000/v1/hooks/<hidden>/notify`);
- right after the name of a digest and a `:`, `=`, `/` or `-` it is shown at any length:
  `md5`, `sha1`, `sha224`, `sha256`, `sha384`, `sha512`, `blake2b`, `blake2s` or `blake3`
  (`DIGEST_NAMES`), as in `sha256:` and 64 characters;
- any other hexadecimal of 32 characters or more is hidden, 32 and 64 characters among them.
  A checksum of 64 characters without its `sha256:` is hidden too;
- after `0x` or `0X`, the digits after it follow the same rule: `0x` and 32 or more of them is
  hidden (`--seed <hidden>`), `0x` and 40 is shown as a commit id is, and a short value such as
  `0xdeadbeef` is shown.

An AWS access key id has a shape of its own, and is hidden wherever it stands though it is
shorter than 32 characters: one of the prefixes `AKIA` and `ASIA` (`ACCESS_KEY_ID_PREFIXES`),
which the [IAM identifiers](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html#identifiers-prefixes)
page of the AWS documentation gives for an access key and a temporary access key, followed by
capitals and digits to 20 characters in all (`ACCESS_KEY_ID_LENGTH`). So a key id under a name
that names nothing is hidden too: `MODEL_NAME=<hidden>`. The id is read as a whole part of
letters and digits, so one glued to more letters or digits, as in `X` and an id, is shown. The
other ids of that page, such as a user id that starts with `AIDA`, and a code of 20 capitals and
digits with any other prefix are shown.

Ordinary values stay shown: paths made of words, numbers, flags, version strings such as
`2.5.1+cu124`, model names such as `made-up/Model-3B-Instruct-FP8`, identifiers written in
CamelCase, also with capitals and digits such as `FP16` or `V2`, or with underscores, UUIDs and
device ids that hold one, short ids, 40-character commit ids on their own or after their
folders, and `sha256:` digests.

**A generated token that fails one of the tests still shows**: one under 32 characters, also
after a short prefix of its own, unless it has the shape of an AWS access key id; one without both capitals and small letters, such as 40 small
letters and digits; and the few random values that fail test 3, 4 or 5 by chance. A base64
value written with `/` and neither `+` nor padding shows a part at either end of it that reads
as a word of a path, such as `x9` or `ab`, as above, and a base64url value, written with `-` and
`_`, without padding, shows its parts under 32 characters. Inside a path, a base64 value written
with `/`, with or without `+`, shows whole when what lies between the words of the path at its
ends, read with up to two short words beside it, is under 32 characters, as when a part at one
of its ends reads as a word of three small letters or more (`made9`). A base64 value written with percent escapes, as in a query value under a name that
names nothing (`?part=`), shows whole when the text it stands for and each part of that text
fail a test by chance; a value near 32 characters does so more often than a longer one. Under
a credential-like query name, such as `token`, `sig` or `signature`, it is hidden by its name.
Pass such a token in an environment variable.

## Keys

`NAME` stands for a name you choose.

### `[run]`

| Key | Default | Meaning |
|---|---|---|
| `run.rounds` | `"auto"` | the round count, or `"auto"` |
| `run.rounds_exact` | `false` | run exactly `run.rounds`, even when unbalanced |
| `run.quick` | `false` | the smallest balanced round count |
| `run.budget` | none | a duration; the largest balanced count whose estimate fits |
| `run.warmups` | 1 | discarded launches per side before round 1 |
| `run.same_vs_same` | `"on"` | `"on"`, `"off"`, or a list of the sides that get a twin |
| `run.allow_underpowered` | `false` | run fewer rounds than can give a verdict |
| `run.out` | `pairbench-runs/<time>-<id>` | the run folder |
| `run.print_plan` | `false` | print the plan and exit |
| `run.json` | `false` | print the results document on standard output |
| `run.no_plugins` | `false` | load no plug-in outside the package |
| `run.node_type` | none | a label for the class of machine, recorded in the results |
| `run.vary_env_size` | `false` | change the size of the environment from round to round |

### `[workload]`

| Key | Default | Meaning |
|---|---|---|
| `workload.argv` | none | the workload, as a list; the words after `--` on the command line |
| `workload.driver` | `"wall"` | the driver that reads each launch |
| `workload.levels` | `[1, 8, 32]` when every side serves and levels count concurrency, else none | the load levels of a serving experiment, a list of numbers |
| `workload.level_duration` | `"60s"` when every side serves, except with the `vllm-bench` driver; else none | the length of each load level |
| `workload.level_kind` | `"concurrency"` | what a level counts: `"concurrency"` or `"rate"` (requests per second) |

### `[sides.NAME]`

Each side has exactly one of the kind keys `image`, `cmd`, `python`, `venv`, `conda`, `serve`,
`file` or `kind`.

| Key | Meaning |
|---|---|
| `sides.NAME.image` | an image side: the image reference |
| `sides.NAME.args` | an image side: the command run in its container, in place of the shared workload; without it the container runs the workload |
| `sides.NAME.env` | an image side: environment variables of the container, a table |
| `sides.NAME.entrypoint` | an image side: the entrypoint to use instead of the image's; the shared workload is read after it, as [what the shared files hide](#what-the-shared-files-hide) says |
| `sides.NAME.cmd` | a command side: the command, a list; an item `{workload}` is replaced by the workload |
| `sides.NAME.python` | a Python side: an interpreter by name or path |
| `sides.NAME.venv` | a Python side: a virtual environment folder |
| `sides.NAME.conda` | a Python side: a conda environment by name or prefix |
| `sides.NAME.file` | a file side: result files, a list of paths or globs, one file per round |
| `sides.NAME.format` | a file side: the driver that reads the files |
| `sides.NAME.kind` | a side of a kind a plug-in adds |
| `sides.NAME.spec` | the spec of a plug-in side |
| `sides.NAME.baseline` | `true` makes this side the baseline |

### Serving sides

`[sides.NAME.serve]` describes a server; `[workload]` names the load driver and its levels.
A serving side needs a load driver: `guidellm`, `aiperf`, `vllm-bench` or one a plug-in adds.
The built-in load drivers need at least one level. A load driver with a side that runs its
own command is refused. These are checked before any side is looked up.

```toml
[sides.new.serve]
image = "REGISTRY/server@sha256:NEW_DIGEST"
args = ["--model", "/models/m"]
port = 8000
ready = { http = "/health", timeout = "15m" }
```

| Key | Default | Meaning |
|---|---|---|
| `sides.NAME.serve.image` | none | the server image; give this or `command` |
| `sides.NAME.serve.args` | `[]` | the server's arguments |
| `sides.NAME.serve.port` | 8000 | the port the server listens on |
| `sides.NAME.serve.ready.http` | `"/health"` | the path polled until the server is ready |
| `sides.NAME.serve.ready.timeout` | `"15m"` | the longest wait for readiness |
| `sides.NAME.serve.env` | `{}` | environment variables of the server, a table |
| `sides.NAME.serve.model` | none | where the model is |
| `sides.NAME.serve.model_name` | none | the model name the load tool asks for; default: from the server's list of models |
| `sides.NAME.serve.launcher` | follows `launch.engine` | how the server is started: `docker`, `podman` or `host` |
| `sides.NAME.serve.command` | none | the server command for the `host` launcher, in place of `image` |
| `sides.NAME.serve.probe.path` | `"/v1/chat/completions"` | the path of the one small request sent after readiness |
| `sides.NAME.serve.probe.body` | a small streaming chat request | the body of that request, a table |
| `sides.NAME.serve.phases` | the built-in patterns `weights_loaded`, `engine_ready` and `server_started`, start-up lines of the vLLM OpenAI-compatible server as its [source at v0.33.0](https://github.com/vllm-project/vllm/tree/v0.33.0) prints them | start-up phases: a table from a phase name to a regular expression matched against the server's log; a table that names at least one phase replaces the built-in patterns, and an empty table keeps them. A phase is timed when pairbench reads its line; the loud note `startup_phases_read_late` names the phases whose line was read after the first answer, and `startup_phases_left_out` names those left without a time because the reader had not caught up 30 s after the first answer; each is given once per entry of the lineup, a twin under its own name, from the rounds that complete only, and for the positive control only when a phase it names is a primary case |

### `[launch]` and `[sides.NAME.launch]`

`[launch]` applies to every side; `[sides.NAME.launch]` overrides a setting for one side.
Every difference between sides is printed in the plan under "sides differ in" and recorded.
A setting a kind of side cannot honour is refused, never dropped: `memory`, `mounts` and
`network` on command and Python environment sides.

| Key | Default | Meaning |
|---|---|---|
| `launch.cpus`, `sides.NAME.launch.cpus` | none | pin every launch to these CPUs, for example `"4-7"` |
| `launch.gpus`, `sides.NAME.launch.gpus` | none | `"all"` or a comma-separated list of GPU indices, numbered as `nvidia-smi` numbers them; a host side gets `CUDA_VISIBLE_DEVICES` with `CUDA_DEVICE_ORDER=PCI_BUS_ID` unless its `env` table sets the order, and an index this machine does not have is refused, naming the side when the index is in that side's own setting |
| `launch.memory`, `sides.NAME.launch.memory` | none | the memory limit of a container, for example `"8g"` |
| `launch.env`, `sides.NAME.launch.env` | `{}` | environment variables, a table |
| `launch.env_pass`, `sides.NAME.launch.env_pass` | `[]` | variables forwarded from the caller, values not recorded |
| `launch.mounts`, `sides.NAME.launch.mounts` | `[]` | mounts of a container, in the engine's `SOURCE:TARGET[:OPTIONS]` form |
| `launch.workdir`, `sides.NAME.launch.workdir` | none | the working directory; two sides with one fingerprint in two working folders are two sides ([`E_SAME_SIDE`](exit-codes.md#e_same_side)) |
| `launch.network`, `sides.NAME.launch.network` | none | the network of a container |
| `launch.timeout`, `sides.NAME.launch.timeout` | none | the longest one launch may take; on a serving side, from the server start to the end of its load (the waits for a free GPU before the start and for its memory after the stop keep their own limits); `pairbench plan` warns of a side whose timeout is shorter than its serving load, or, for the baseline, than the load a launch of the positive control runs twice; a launch that runs into it stops the run, and its record in the capture says `"timed_out": true` for every kind of side |
| `launch.engine`, `sides.NAME.launch.engine` | `"auto"` | `"auto"`, `"docker"` or `"podman"`; each question to the engine (its version, its facts, an image's details) has 60 s to answer, and an image the engine does not answer about in time is refused with `E_SIDE_UNRESOLVED`, never pulled. When sides launch with different engines, the recorded `engine` is the first side's and the note `engines_differ` names the engine of each side |
| `launch.pull`, `sides.NAME.launch.pull` | `"missing"` | `"missing"`, `"never"` or `"always"`; applies before the run only; a pull has no time limit |
| `launch.identify`, `sides.NAME.launch.identify` | none | a command, as a list, run once inside each side to identify it |
| `launch.perf_counters`, `sides.NAME.launch.perf_counters` | `false` | give a container the capability to use performance counters, and nothing else |
| `launch.allow_identical` | `false` | allow two sides with the same fingerprint |

### `[gates]`

| Key | Default | Meaning |
|---|---|---|
| `gates.mode` | `"warn"` | `"off"`, `"warn"` or `"enforce"` |
| `gates.wait_quiet` | `false` | wait until the machine is quiet before starting; refused with `gates.mode = "off"`, which skips the checks before the run |
| `gates.locks` | `[]` | advisory lock files, taken in order |
| `gates.lock_timeout` | `"30m"` | the longest wait for the locks |
| `gates.allow_mixed_core_types` | `false` | allow a CPU set that mixes core types |
| `gates.quiet.max_busy_cores` | 1.0 | busy cores, summed over the machine, that still count as quiet |
| `gates.quiet.gpu_idle` | `true` when a side selects a GPU | require no other compute process on the GPUs any side selects |
| `gates.quiet.samples` | 5 | consecutive quiet samples needed |
| `gates.quiet.interval_s` | 2 | seconds between samples |
| `gates.quiet.max_wait_s` | 1800 | the longest wait, then the check fails |
| `gates.census.max_busy_cores` | 0.5 | busy cores above which another container fails the census |
| `gates.discard.max_busy_cores` | 2.0 | busy cores of others above which a launch is disturbed |

### `[rule]` and `[cases]`

| Key | Default | Meaning |
|---|---|---|
| `rule.name` | `"strict"` | the verdict rule; the other fields of a rule are set through the Python API or a rule plug-in |
| `rule.fail_on` | `[]` | outcomes of a primary case that make the exit code 1 |
| `cases.primary` | the driver's default | glob patterns of the primary cases |
| `cases.groups.NAME` | none | glob patterns of cases that share one noise floor |

### `[energy]`

| Key | Default | Meaning |
|---|---|---|
| `energy.enabled` | `false` | sample GPU power during the load phase |
| `energy.interval_s` | 0.2 | seconds between power samples |
| `energy.min_samples` | 10 | the fewest samples a window needs for a value; at least 2 |

### `[report]`

| Key | Default | Meaning |
|---|---|---|
| `report.include_image_refs` | `false` | show the image references of image and serving sides in the results |
| `report.html` | `true` | write `report.html` |

With `report.include_image_refs` on, the results show image references as typed, local
archive paths included. `sides[].image_ref` and the recorded command in `results.json`,
`results.md` and `report.html` keep a reference such as `registry.example/team/app:2.0`
with its registry and `oci-archive:/made/up/new.tar` with its folders.

### `[controls]` and `[launch_cost]`

| Key | Default | Meaning |
|---|---|---|
| `controls.positive` | `"on"`, `"off"` for a serving experiment | the positive control |
| `controls.positive_tolerance` | 0.10 | how far the control may read from its expected value, as a fraction of it |
| `controls.positive_via` | `"repeat"` | `"repeat"` runs the workload twice in one start; `"factor"` runs it once with `PAIRBENCH_WORK_FACTOR=2` |
| `launch_cost.launches` | 20 | empty launches timed during warm-up; 0 turns the measurement off |
| `launch_cost.note_share` | 0.01 | the share of a `wall` value above which the launch-cost note is given |

### `[explain]` and `[plots]`

| Key | Default | Meaning |
|---|---|---|
| `explain.mode` | `"always"` | `"always"`, `"auto"` or `"off"` |
| `explain.sample_hz` | 99 | stack samples per second |
| `explain.call_graph` | `"fp"` | how call graphs are collected: `"fp"`, `"dwarf"` or `"lbr"` |
| `explain.top` | 20 | how many functions and shared objects are kept per side |
| `plots.mode` | `"auto"` | `"auto"` draws the charts when the `plot` extra is installed; `"on"` refuses without it; `"off"` |
| `plots.max_round_charts` | 12 | the most round-by-round charts that are drawn |
