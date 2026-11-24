# Security policy

## Reporting a vulnerability

Please report a vulnerability privately, through the private vulnerability reporting of the
source repository: open <https://github.com/eugo-inc/pairbench/security/advisories/new>, or
choose "Report a vulnerability" on the repository's Security tab. Do not open a public
issue for it.

Say what the problem is, how to reproduce it, and what it lets an attacker do. We will
answer in the advisory thread, and credit you in the advisory if you wish.

## A config is code

A pairbench config file launches containers and commands on your machine: every side is a
command line, an image or an interpreter, and the workload runs as you. Treat a config from
someone else as code. Read it before you run it, as you would read a script.

For that reason pairbench never picks up a config file by itself; only `--config` or
`PAIRBENCH_CONFIG` loads one. The tool server for AI agents starts and cancels runs only
when it is started with `--allow-run`.

## What results may hold

A results document is meant to be shared. It holds no host name, user name, path outside
the run folder or value of the environment, except an image reference you ask for and the
forms listed under [known limits of the shown command](#known-limits-of-the-shown-command),
such as a host or a user written without a scheme.
With `report.include_image_refs` on, the results show image references as typed, local
archive paths included, so a reference names its registry and a local archive names its
folders. The recorded command in `results.json`,
`results.md` and `report.html` hides the secret forms listed in
[what the shared files hide](docs/reference/config.md#what-the-shared-files-hide). A short
plain value that nothing on that list names is shown: one given after an option of one
letter, as a plain argument or in the path of an address. A host or a user written without a
scheme is shown too, and a case id keeps a host and a user, as the
[known limits](#known-limits-of-the-shown-command) say. The hashes a results document
shows of each side and of the config, `argv_sha256`, `args_sha256`, `identify_sha256`,
`fingerprint` and `config_sha256`, are computed with the recognised secret forms hidden: each
such value is replaced by `<hidden>` before hashing, so a guess at it cannot be checked
against a hash. The case patterns of the config are the exception the
[known limits](#known-limits-of-the-shown-command) name: `config_sha256` takes them as typed.
A file side's `fingerprint` is the other exception: it covers each of the side's result files
as it is, a secret in a case id the file holds included, as the
[known limits of the hashes](#known-limits-of-the-hashes) say.
The output of a side's `identify` command is read line by line for its credentials
only: a checksum, a build id or another long value it prints is in the hash as printed, since
it is what tells one build of a side from another. A
value in a form the tool does not recognise is still in the hash, and someone who knows the
rest of the command can confirm a guess at it by hashing the guess. So give a side a secret
through the environment with `env_pass`, listing its name under `launch.env_pass`: no file
records its value and no hash covers it. The capture and the diagnostics are for the person
who ran the benchmark: the capture keeps the command line as typed, credentials included, and
the diagnostics hold names from the measured code. pairbench creates the capture, and the files
that hold what each process, load step and server printed, readable and writable by their owner
only (mode `0600`), so other users of a shared machine cannot read them; a new results file
(`results.json`, `results.md`, `report.html`) is made readable by all (mode `0644`) whatever the
umask, and one already there keeps its mode, since they are meant to be shared. The files of
the explain step, `diagnostics.json` and the folded stacks, differences and flame graphs under
`profiles/`, are owner-only too, and so is what its instruments print while they run;
`report.html` embeds the diagnostics and the flame graphs when the step ran. A file that another
program writes into a launch's folder, such as the export a driver reads, the report `nsys` or
`ncu` writes for `pairbench profile` or a file your workload writes, has the mode that program
gives it while the launch runs, which under a umask of `022` lets every user read it; when the
launch ends, pairbench takes the group's and others' permissions off every such file you own. A
file that the container of an `image` side, or the server's container of a serving side, writes
as another user, such as root, is handed back to you before that, with one short container of
the same image that runs `chown`, however the launch ends, an interrupt or an error included.
When pairbench cannot hand such files back, for example when the engine cannot be reached or a
second interrupt stops the hand-back, a note on standard error and in the results names the
launch folder whose files still belong to the image's user and may be readable by other users;
such a file keeps its mode. A folder that such a program or container makes in a launch's folder
keeps the mode it was made with, so other users may be able to list the names in it.
`plan.tsv`, which holds the side names and the round order, and the charts under `charts/`,
which draw what `results.json` holds, have the mode your umask gives, and so do the run folder
and the folders pairbench makes in it: under a umask of `022` every user can read them and list
the names in those folders, but cannot open a file in them that is owner-only. If you find a
results document that leaks something it should not, report it as above.

## What the terminal shows

A line pairbench prints on standard error (a refusal, a note, a machine check that did not
pass) and the text of `pairbench plan` escape what they show of an input, such as a side, case
or file name: a control character is written as `\n` or `\x1b`, a line or paragraph separator,
a Bidi_Control character or a lone surrogate as `\uNNNN`, and a backslash as `\\`. Such a name
then cannot move the cursor, change the colours, start a line that looks like one of the tool's
own or change the order a line shows in, and each printed line stands for one text only. A name
that a message quotes keeps the escapes of its quoting, so their backslashes show doubled. The
terminal report shows a control character, a separator, a Bidi_Control character or a lone
surrogate as `?` and prints a backslash as it is. The results document, `plan.tsv` and
`pairbench doctor --json` keep each name as it is.

## Known limits of the shown command

The recorded command is cleaned by the shape of what it holds, so these forms of address and
of names are not read as you may mean them:

- **A host part no host name has.** A `file://` address whose host part holds a character no
  host name can hold, such as a comma or a colon with no port number after it, is not read as
  an address with a path, so its folders show as typed. The host ends at a comma and is
  hidden, and a host before such a colon shows too: `file://a,b/made/up/c` shows
  `file://<hidden>,b/made/up/c`, and `file://h:x/made/up/y` shows whole.
- **Two addresses written together.** Two addresses with no space between them are read as
  one, so the host of the second can show: `file://a.binhttps://made-up.example` shows
  `file://made-up.example`.
- **A password word glued to another word.** A password word glued to a word that is not one
  of the endings the config reference lists, such as `FILE`, `PATH` or `VALUE`, is read as one
  word with the word after it, so the name is not read as a credential and its value shows:
  `PASSNOTE=madeup` shows whole, while `PASS_NOTE=madeup` shows `PASS_NOTE=<hidden>`.
- **A key glued to a word that begins like an ordinary word.** A name that starts with a key
  glued to a word that begins like one of the ordinary words the config reference lists, such
  as `KEYPAD` or `KEYMAP`, is read as that ordinary word, so its value shows:
  `KEYPADDING=madeup` shows whole, while `KEY_PADDING=madeup` shows `KEY_PADDING=<hidden>`.
- **A key written with `/` and neither `+` nor padding.** A base64 value written so is read
  as a path when a part at either end of it reads as a word of a path, such as `ab` or `x9`, and
  that part shows: `ab/EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw` shows `ab/<hidden>`. Such
  a key that fails one of the tests the config reference gives for a random-looking value, as
  a few generated values do by chance, shows whole. So does such a key each part of which
  between two `/` reads as a name, as the config reference says a part of a path does, which a
  few generated values do by chance: `EXAMPLE7KqpbnaOKWGQ9GRST/BjCwHeizXolJuj` shows whole.
  Inside a path, such a key, and one written with `+`, shows whole when what lies between the
  words of the path at its ends, read with up to two short words of a path beside it, is under
  32 characters, as when a part at one of its ends reads as a word of three small letters or
  more, which a few generated values do by chance:
  `data/EXAMPLETailFak/zQ9zQx9XyTAILRea/made9/out.json` shows whole. Such a key can also show
  whole in a path with a folder that is no word of a path and holds a capital, a digit or a `-`,
  such as `SRV`, `srv2`, `Data-X` or `Documents`, as some generated values do:
  `SRV/NFS/EXAMPLETailFakezQ9/zQx9XyTAILRealUP/out.json` shows whole.
- **A path written with `\` or split at a blank.** A path written with `\` between its folders
  is not read as a path, so its folders show as typed: `C:\Users\Zq Name\x.txt` shows whole. In
  the name of a command that hyperfine runs, a path with a blank in a folder name and no quotes
  around it is read as the shell splits it, as two words, so the parts of the folder name on
  both sides of the blank show: `tool /srv/Zq One/x.txt` shows `tool Zq One/x.txt`.
- **A path that starts with three `/` or more inside a word.** In a shell text, in the value of
  an option or a variable and in the query of an address, a path that starts with three `/` or
  more is not read as a path, so its folders show as typed: `sh -c 'cat ///made/up/x.txt'`,
  `--in=///made/up/x.txt` and `https://made-up.example/v1?file=///made/up/x.txt` show the
  folders. An argument that starts so is cut (`cat ///made/up/x.txt` shows `cat x.txt`), and so
  is a path inside a word that starts with one or two `/` (`--in=//made/up/x.txt` shows
  `--in=x.txt`); write the path with one `/` at its start.
- **A path quoted in part in a shell text.** In a shell text, a path in quotes is cut to its
  last part when the quotes are around the whole path. A word with quotes around only some of
  its folders is read as paths that end at each quote, so the folder names in quotes show:
  `cat '/srv/Zq Files'/x.txt` shows `cat 'Zq Files'x.txt`, and `cat /srv/'Zq Files'/x.txt`
  shows `cat srv'Zq Files'x.txt`.
- **A home folder under another folder.** A path whose last part is a home folder shows
  `<hidden>` in its place when that folder is right under `/home` or `/Users`, at the root or
  reached by climbing with `..`, or is written `~made-up-user`. A home folder kept under any
  other folder is read as an ordinary folder, so its name shows as the last part:
  `tool /var/home/user` shows `tool user`. So does a file named after its user
  (`tool ../made-up-user.txt` shows `tool made-up-user.txt`), and so does a home written
  `~made-up-user` glued to a short option, which is read as part of the option
  (`tool -d~made-up-user` shows as typed). Write your own home folder as `~`, which shows as
  typed, or name a file inside it, and give an option its folder as a word of its own.
- **A home folder's name in a case id.** A case id keeps the name of a home folder, since in
  the name of a test or a benchmark such a name is often no home, and two ids that differ only
  there are two cases. A word that starts with `~` and a name, with nothing after it, shows as
  typed (`test_invert[~mask]`, `test_dtor[~Widget]`), and a path that ends at a folder right
  under `/home` or `/Users`, at the root or reached by climbing with `..`, is cut to that
  folder's name, as any path in a case id is cut to its last part, since a route reads the same
  (`test_get[/users/1]` shows `test_get[1]`). So a user's home shows its name:
  `test_read[~made-up-user]` shows as typed, `test_read[/home/user]` shows `test_read[user]`,
  and so does a case that `hyperfine` names after the command `ls ~made-up-user` or
  `ls /home/user`, while the shown command hides that home. A path that goes on into the home
  is cut to its last part (`test_read[~made-up-user/x.csv]` shows `test_read[x.csv]`). Name a
  file inside the home, write your own home as `~`, or give the case a name, as hyperfine's
  `--command-name` gives one.
- **A path after a variable, or joined in code.** A path that starts with a variable, such as
  `$HOME/Zq Files/x.txt`, is not read as an absolute path, so its folders show as typed. Of a
  path that a program joins from parts, such as `Path('/srv') / 'Zq Files' / 'x.txt'`, each
  part after the first shows.
- **A string in code read only in part.** In code, a credential's value is hidden to the
  quote, the mark or the end word that closes it, with the strings joined to it. These forms
  are read only in part, so the rest of the value shows: an f-string of Python that uses its
  own quote inside its braces, as `python3 -c 'token = f"made {d["k"]} VALUE"'` shows
  `python3 -c 'token = <hidden>k"]} VALUE"'`; a string with a tag before it in JavaScript, as
  ``node -e 'const token = String.raw`made VALUE`'`` shows
  ``node -e 'const token = <hidden> VALUE`'``; a raw string of Julia or of Swift, as
  `julia -e 'token = raw"made VALUE"'` shows `julia -e 'token = <hidden>"made VALUE"'` and
  `swift -e 'let token = #"made VALUE"#'` shows `swift -e 'let token = <hidden>"made VALUE"#'`;
  a raw string of C++ that names an end word and holds a quote, as in `R"x(made " VALUE)x"`,
  where what follows that quote shows; a second string on the next line inside the brackets
  of a call with nothing between the two, as in `connect(token='made '` with `'VALUE')` on
  the next line, where `'VALUE'` shows; and a here-document of Ruby opened inside brackets, as
  in `token = (<<~EOT)` with `made VALUE` and `EOT` on the lines after it, whose lines show.
- **A join of Perl or PHP read only in part.** A credential's value joined with `.` is hidden
  with the plain variables and strings joined to it, but not every join is read whole. A
  here-document joined after an element of an array, as in
  `perl -e 'my $token = "made" . $a[0] . <<EOT;'` with `password` and `EOT` on the lines after
  it, or after a variable that stands on a line of its own or has no blanks around its `.`, is
  not read with the value, so its lines show. In PHP, after an element of an object's property,
  such as `$o->p[0]` or `$this->cfg["k"]`, a static property or an element of one, such as
  `C::$p` or `C::$p[0]`, or a property of an element, such as `$o["k"]->p`, the string joined
  to it shows:
  `php -r '$token = "made" . $o->p[0] . "password";'` shows
  `php -r '$token = "<hidden> . "password";'`. So does a string joined after a call, a
  constant, an array or a numbered variable, such as `f()`, `getenv("X")`, `PHP_EOL`, `@x` or
  `$1`.
- **A folder name with a word that starts with a mark.** In a shell text, a case id or a free
  text, a path runs on over the blanks of a folder name to words that start with a letter, a
  digit or `_`. A folder name with a word that starts with a mark, such as `&`, `-`, `,`, `(`
  or `[`, or with a blank that is not a space or a tab, such as a no-break space, can end the
  path at that blank, and the rest of the name shows: `test_read[/srv/Zq & Co/x.csv]` shows
  `test_read[Zq & Co/x.csv]`. A word of a command that starts as an absolute path is cut whole.
- **A path after an option or a `<` in a case id.** A case id is read so that the `/` that
  joins the parts of a name is kept, so a path glued to an option or written after a `<` shows
  whole: `test_build[-I/srv/Zq/include]` and `read </srv/Zq/x.txt` show as typed.
- **A folder name with a blank in a path written with `%2F`.** A path that writes each `/` as
  `%2F` ends at a blank, so the words of a folder named with blanks show, in the shown command
  and in a case id: `get[?host=%2Fmade%2FZq dir%2Frun]` shows `get[?host=%2FZq dir%2Frun]`, and
  two sides whose folders differ there name the case apart, so the run is refused with
  `E_CASES_DIFFER`. Written with `%20` for each blank, as in
  `get[?host=%2Fmade%2FZq%20dir%2Frun]`, the folder is cut with the rest and shows
  `get[?host=%2Frun]`, so the sides pair the case.
- **A path after a relative path that stays inside its folder.** A relative path with `..`
  parts that stays inside its folder, such as `x/../y` or `lib/../lib`, is kept as typed to the
  end of its word, so a path that follows it in the same word shows its folders:
  `tool --path=lib/../lib:/made/up/lib` shows whole. In the query of an address such a path ends
  with its query parameter, and a path that starts at one `/` or at `~`, or a local address,
  after it is cut: `psql 'postgresql://db.example/db?k=a/../b:/made/up/ca.pem'` shows
  `psql 'postgresql://<hidden>/db?k=a/../b:/ca.pem'`. After a host name or a port number, with a
  path after it or none, and after an empty host, an empty port, a user, a host and an empty port
  or a host in brackets with no path after it, right before the query or the fragment, as in
  `postgresql://?k=x`, `postgresql://:?k=x`, `postgresql://@:?k=x`, `postgresql://db.example:?k=x`
  and `postgresql://[::1]?k=x`, the words after a blank in such a query parameter that no path runs
  on over are kept as typed to its end, so a path there shows its folders, and a path in a later
  parameter is cut. They are cut with a path after anything else, as in `postgresql:///db?k=x`,
  which has no host, `postgresql://[::1]/db?k=x` and `postgresql://db.example:/db?k=x`, with a path
  in a `file://` address, or one whose scheme ends in `file`, in a `unix://` address, or one whose
  scheme ends in `+unix`, with no user, host in brackets or socket path written with `%2F` before
  the query or the fragment, as in `unix://?k=x`, and in the shown command after a scheme of one
  letter, as in `x://?k=x`. After a host in brackets in such a `unix://` address, as in
  `unix://[::1]?k=x`, a path in a later parameter shows too:
  `psql 'postgresql://db.example/db?k=a/../b x/c:/made/up/ca.pem&j=/made/up/ca.pem'` shows
  `psql 'postgresql://<hidden>/db?k=a/../b x/c:/made/up/ca.pem&j=/ca.pem'`. A word and two `/`
  after it are read as an address with a host, whose path shows:
  `psql 'postgresql:///db?k=a/../b://made/up/ca.pem'` shows
  `psql 'postgresql:///db?k=a/../b://<hidden>/up/ca.pem'`. A climbing path after it in the same query
  parameter is read with it as one path, in which `b:..` is a folder, so its folders show
  unless that one path climbs out of its folder:
  `psql 'postgresql://db.example/db?k=a/../b:../../made/up/ca.pem'` shows
  `psql 'postgresql://<hidden>/db?k=a/../b:../../made/up/ca.pem'`, and
  `psql 'postgresql:///db?k=a/../b:./../made/up/ca.pem'` shows whole, while
  `psql 'postgresql://db.example/db?k=a/../b:../../../made/up/ca.pem'` shows
  `psql 'postgresql://<hidden>/db?k=ca.pem'`. After a `;`, a comma, a bracket or a
  quote in the query, in the query of an address with a bracket in its path, and in the query
  of an address with two hosts or more, the words are read as any others, so a path that
  follows such a path there shows its folders, a local address and a climbing path too:
  `psql 'postgresql:///db?a=b;k=x/../y&j=file:///made/up/ca.pem'` shows whole,
  `psql 'postgresql:///a[b]?k=a/../b&j=/made/up/ca.pem'` shows whole, and
  `psql 'postgresql://db1.example,db2.example/db?a=b/../c&sslrootcert=../../made/up/ca.pem'`
  shows `psql 'postgresql://<hidden>/db?a=b/../c&sslrootcert=../../made/up/ca.pem'`. With no
  such path before it, a path there is cut:
  `psql 'postgresql:///db?a=b;sslrootcert=file:///made/up/ca.pem'` shows
  `psql 'postgresql:///db?a=b;sslrootcert=file://ca.pem'`. After the same hosts, and cut where
  those words are cut except after a scheme of one letter, a query parameter of such a path that
  holds an address with a host shows whole, with a `/` put before it, or with none after a host
  in brackets in a `unix://` address:
  `psql 'postgresql://db.example/db?k=a/../b:/made/up/x/s3://db2.example/y'` shows
  `psql 'postgresql://<hidden>/db?k=/a/../b:/made/up/x/s3://<hidden>/y'`. A case id keeps
  such a path as typed with an absolute path right after it and a `:`, `=` or `@`, so that path
  shows its folders, and reads a climbing path after it with it as one path, as the shown
  command does, with no host before them, after a host and an empty port, and after an earlier
  path in the query of an address with one host:
  `test_conn[postgresql:///db?k=a/../b:../../made/up/ca.pem]` and
  `test_conn[postgresql:///db?k=a/../b:/made/up/ca.pem]` show whole. In a case id, after a
  single host, with a port number or none, in brackets or not, and with no path, `;`, comma,
  bracket or quote before it in the query or the fragment, the query parameter of such a path
  shows whole, with a `/` put before it, so a path after it in that parameter shows its folders:
  `test_conn[postgresql://db.example/db?k=a/../b:/made/up/ca.pem]` shows
  `test_conn[postgresql://db.example/db?k=/a/../b:/made/up/ca.pem]`.
- **A local address or a climbing path that runs into another address.** In the query or the
  fragment of an address with no host, a host and an empty port, a host in brackets with no port, a
  `unix://` socket, the path of a `file://` address or an earlier path in the query before it, a
  local address ends at the next `&`, `?` or `#`. One that holds a blank before then followed by a
  word with a `/`, which the path runs on over as it does over the words of a folder named in words,
  or that holds another address before then, or a value that looks random, shows as typed, with that
  value hidden, and so does a climbing path that holds such a blank and word before the next `&`,
  `?` or `#`, another address or such a value, so the host of the other address is hidden: `psql
  'postgresql:///db?c=../made/up/s3://db.example/x'` shows `psql
  'postgresql:///db?c=../made/up/s3://<hidden>/x'`, and `psql
  'postgresql:///db?sslrootcert=file:///made/Zq Files/ca.pem'` shows whole. A blank with no such
  word after it ends the path, which is cut: `psql
  'postgresql:///db?sslrootcert=file:///made/up/ca.pem fast'` shows `psql
  'postgresql:///db?sslrootcert=file://ca.pem fast'`. After a host name or a port number, with no
  path before it in the query, a local address there ends at the next `?` or `#` only, so an address
  after it in the same query is read as a part of its path, whose last part shows that address's
  host: `psql 'postgresql://db.example/db?c=unix:///made/up/s.sock&next=https://db2.example:443?x'`
  shows `psql 'postgresql://<hidden>/db?c=unix:///db2.example:443?x'`.
- **A host after a port or a host in brackets.** In an address with two hosts or more, the
  hosts after a port show, and so do the hosts after a host in brackets and a host in brackets
  after the first: `psql 'postgresql://db1.example:5432,db2.example:5433/db'` shows
  `psql 'postgresql://<hidden>:5432,db2.example:5433/db'`,
  `psql 'postgresql://[fd00::1],db2.example:5433/db'` shows
  `psql 'postgresql://<hidden>,db2.example:5433/db'`, and
  `psql 'postgresql://db1.example,[fd00::2]:5433/db'` shows
  `psql 'postgresql://<hidden>[fd00::2]:5433/db'`. Host names with a port on the last host only
  are hidden together: `psql 'postgresql://db1.example,db2.example:5433/db'` shows
  `psql 'postgresql://<hidden>:5433/db'`.
- **A credential after a second `?` in an address.** In the query of an address, a `?` inside
  a value starts no parameter, so a credential after it is read as a part of that value and
  is not hidden: `curl 'https://made-up.example/v1?next=/a?token=made-up'` shows
  `curl 'https://<hidden>/v1?next=/a?token=made-up'`. Written before that value, it is
  hidden: `curl 'https://made-up.example/v1?token=made-up&next=/a?b'` shows
  `curl 'https://<hidden>/v1?token=<hidden>&next=/a?b'`.
- **A commit id's length joined to a path in a query in another way.** Hexadecimal of 40
  characters, the length of a commit id, shows on its own. In the query or the fragment of an
  address it is hidden when it follows a `?`, `&`, `#` or `=` and a `.` joins it to a path after
  it, as the config reference says. These forms of it there are read as a commit id and show:
  after another character, such as a `:`, a `!` or a percent escape; glued to a `-`, a `_` or a
  `~`; or joined to the path by a percent escape. With `<id>` for the 40 characters,
  `curl 'https://made-up.example/x?:<id>./../b'` shows `curl 'https://<hidden>/x?:<id>./../b'`,
  and so do `?!<id>./../b`, `?k=a:<id>./../b`, `?k=%20<id>./../b`, `?<id>-./../b`,
  `?<id>_./../b`, `?<id>~./b`, `?<id>%2e./b` and `?<id>.%2Fb`. So does such a value followed by
  only `./` at the end of an address that has a `&` and no `?`, which is cut as a path before the
  value is read: `curl 'postgresql:///db&<id>./'` shows `curl 'postgresql:///db&<id>.'`. Give a
  secret value after a credential's name: `curl 'https://made-up.example/x?token=<id>./../b'`
  shows `curl 'https://<hidden>/x?token=<hidden>'`.
- **A Redis command a client reads from its input.** A command that a program writes to the
  input of `redis-cli` or `valkey-cli`, as in `echo 'AUTH password' | redis-cli`, is an
  argument of that program and is not read as a Redis command, so its password shows.
- **A client's option in a variable another command reads.** The value of an ordinary name is
  read with a client's options only when a later word of the same command names the client. A
  variable that one command sets and a later command, a script or a shell text reads, as in
  `REDIS_ARGS='-a password'; redis-benchmark $REDIS_ARGS`,
  `env 'REDIS_ARGS=-a password' ./run-redis.sh` or
  `CMD='AUTH password'; memtier_benchmark --command "$CMD"`, is not read with the client's
  options or as the command text a client's option takes, so its password shows.
- **A client's option in a comment after another command.** The words of a comment are read
  with a client's options only when the command right before the comment is a client's command.
  After a pipe or an operator that starts another command, a client's password option in the
  comment is read as a word of that command, so the password shows:
  `sh -c 'redis-cli PING | grep PONG # -a password'` shows whole. A credential form that the
  argument of any program hides, such as `--token password`, is hidden in any comment.
- **A command that `ssh`, `watch` or `parallel` joins from its words.** `ssh` joins the words
  after its host with blanks and hands what it joined to a shell on the other machine, and
  `watch` and `parallel` hand their command to a shell the same way. Each of those words is read
  as a text of its own, so a quote that one word opens and a later word closes is not read as
  that shell reads it:
  `ssh made-up-host memtier_benchmark --command \'AUTH password\'` shows the password. Nor is a
  client's command that one word with blanks starts and a later word goes on:
  `ssh made-up-host 'redis-cli -a' password` and `watch 'redis-cli -a' password` show the
  password. Given as one word, as in
  `ssh made-up-host "memtier_benchmark --command 'AUTH password'"`, the password is hidden.
- **An option of `parallel` or `watch` given its value in the next word.** In the words of
  `parallel`, and of `watch` but for `-n` and `--interval`, an option is read as one word, so
  the value of an option written in the next word, as in `parallel -j 2` or `watch -q 3`, is
  read as the first word of the command. `hyperfine` after it starts no command, and a text
  glued to its `-s`, `-p`, `-c`, `-C`, `--setup`, `--prepare`, `--cleanup`, `--conclude` or
  `--reference` is read as any argument is, so a client's password in that text shows and is
  in the hash: `parallel -j 2 hyperfine "--setup='redis-cli -a password FLUSHALL'" ./bench ::: 1`
  and `watch -q 3 hyperfine "--setup='redis-cli -a password FLUSHALL'" ./bench` show the
  password. With `--` after such an option, as in
  `parallel -j 2 -- hyperfine "--setup='redis-cli -a password FLUSHALL'" ./bench ::: 1`, the
  shown command hides the password and the hash takes it as typed. Written as `-j2` or
  `--jobs=2`, or with the text as a word of its own after `--setup`, the password is hidden in
  both.
- **A client's option written shorter than its name.** A client's password option is read
  by its whole name, as the config reference lists it. A parser such as Python's `argparse`
  also takes a long option shortened to a start that no other option of the program shares,
  and such a shortened option is not read as a password option, so the value after it shows:
  `vllm serve org/model-a --api-ke made-up-key` shows whole.
- **A Redis command its client refuses or reads otherwise.** The command of a Redis or Valkey
  client is read where the client starts it, so in a form the client refuses or reads as
  something else, a password shows: `redis-benchmark -c AUTH madeup` shows whole, since the
  benchmark reads `AUTH` as its count of clients, and so does `redis-benchmark -i 1 AUTH madeup`,
  since the benchmark has no option `-i`. A `MIGRATE` with fewer words before `AUTH` than the
  server reads shows too: `redis-cli MIGRATE made-up-host 6380 AUTH madeup` shows whole.
- **A password given to a script or written to a file.** The words after the `,` of
  `redis-cli --eval` are arguments of the script, and a config line that a side writes to a file,
  through a here-document or `printf`, is text written by another program; neither is read as a
  password: `redis-cli --eval made-up.lua k , madeup` and
  `printf 'requirepass madeup\n' > made-up.conf` show whole.
- **A program or an option that a command substitution gives.** What a command substitution
  prints is not known when the command is cleaned, so a client it names, a client's option it
  gives, or the name of a setting it gives, is not read as one, and the password after it shows:
  `sh -c '$(which redis-cli) -a password'`, `sh -c 'redis-cli $(echo -a) password'`,
  `sh -c 'redis-cli CONFIG SET $(echo requirepass) password'`.
- **A `case` pattern in a command substitution.** The `)` that ends a pattern of `case` inside
  `$(...)` is read as the end of the substitution, so the `;;` after it ends the command around
  it, and a client's password after that shows:
  `sh -c 'redis-benchmark -n $(case x in x) echo 1;; esac) -a password'`.
- **A client named another way.** A client's options and command are read where a word names
  the client, as the config reference lists the clients. A client named through a variable, an
  alias or a shell function, as in `sh -c 'C=redis-cli; $C -a password PING'`,
  `sh -c 'alias r=redis-cli; r -a password PING'` or
  `sh -c 'r() { redis-cli "$@"; }; r -a password PING'`, and a client the config reference
  does not list, as in `keydb-cli -a password PING`, are read as any program is, so the
  password shows. A credential form that the argument of any program hides, such as
  `--pass password`, is hidden there too.
- **A command given in an option of `ssh` or to `--cluster call`.** The value of an option of
  `ssh`, such as `-o RemoteCommand=...`, is read as a value and not as a command, and the words
  that `redis-cli --cluster call` or `valkey-cli --cluster call` sends to each node after its
  address are not read as a Redis command. A client's password there shows:
  `ssh -o 'RemoteCommand=redis-cli -a password PING' made-up-host` and
  `redis-cli --cluster call made-up-host:7000 AUTH password` show whole, and so does a rule of
  `ACL SETUSER` such as `>password` in either. A credential form that the argument of any
  program hides, such as `--password password`, is hidden in the value of an option of `ssh`.
- **A command glued to an option of another name.** Of a program that the config reference
  does not list with its command options, the text glued with `=` to `--command`, `--cmd`,
  `--exec` or `--run` is read as the same text given as the next argument. The text glued to
  an option of any other name is one value, so a client's password in it shows:
  `made-up-tool '--execute=redis-cli -a password PING'` shows whole. Give such a text as the
  next argument: `made-up-tool --execute 'redis-cli -a password PING'` shows
  `made-up-tool --execute 'redis-cli -a <hidden> PING'`.
- **A word in `$'...'` quotes.** A shell reads a word in `$'...'` quotes with its backslash
  escapes turned into the characters they stand for; the shown command does not read such a
  word as the shell does. So in a shell text after `bash -c`, a client's password option in
  them, as in `redis-cli $'-a' password PING`, a rule of `ACL SETUSER`, as in
  `redis-cli ACL SETUSER app on $'>password'`, a client's command, as in
  `memtier_benchmark --command $'AUTH password'`, and the text of an `eval`, as in
  `eval $'memtier_benchmark --command \'AUTH password\''` or
  `eval $'true\nredis-cli -a password PING'`, show the password. In plain quotes, as in
  `redis-cli '-a' password PING`, `redis-cli ACL SETUSER app on '>password'`,
  `memtier_benchmark --command 'AUTH password'` or
  `eval 'memtier_benchmark --command "AUTH password"'`, it is hidden, and so is a password
  that is itself the word in `$'...'` quotes, as in `redis-cli -a $'password' PING`.
- **A host or a user written without a scheme.** The host and the user part of an address are
  hidden only after a scheme such as `https://`. A host or a user written without one is read
  as an ordinary value and shows as typed, after an option of one letter or a long option
  (`tool -h db.example`, `tool -h 192.0.2.10`, `tool -x db.example`, `mysqlslap -h db.example`,
  `tool --host db.example`, `tool --host=db.example`, `tool --user made-up-user`), glued to an
  option (`tool -hdb.example`), as a plain argument (`tool db.example`), as the value of a
  variable (`env DB_HOST=db.example tool`) or of a key in a connection text
  (`psql 'host=db.example user=made-up-user dbname=x'`), with a port
  (`tool db.example:8080/x`), before an `@`, with a password after the user too unless it is
  a long random-looking value (`tool user@db.example`, `tool user:made-up@db.example`), as the
  host of `ssh`
  (`ssh db.example ./bench`, `ssh user@db.example ./bench`) and inside a command text
  (`sh -c 'tool -h db.example'`). Of a host and a path such as
  `scp user@db.example:/made/up/x .`, the path is cut to its last part and the user and the
  host show: `scp user@db.example:x .`.
- **A host or a user in a case id.** The id that a driver reads for a case, such as the id
  of a test, has each absolute path, and each relative path that climbs out of its folder
  (`test_read[../../made/up/x.csv]` shows `test_read[x.csv]`), cut to its last part, the user
  part of an address after a scheme hidden (`test_get[https://bench:made-up@db.example/x]` shows
  `test_get[https://<hidden>@db.example/x]`), and the secret forms the shown command hides
  hidden: the value of a credential-like name or option (`query[PGPASSWORD=made-up]` shows
  `query[PGPASSWORD=<hidden>]`, and `query[--password=made-up]` shows
  `query[--password=<hidden>]`), a password before a host that holds a dot or is followed by a
  port, written without a scheme, up to the `@` before the host, with the text before the user
  and after the host kept (`query[bench:made-up@db.example]` shows
  `query[bench:<hidden>@db.example]`, and `query[bench:made-up@db.example:5432-ro]`, as pytest
  joins two values with a dash, shows `query[bench:<hidden>@db.example:5432-ro]`; such a
  password holds no `@`, quote or angle bracket), and a long random-looking value
  (`query[EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw]` shows `query[<hidden>]`). A
  password before a host is hidden with no user before its colon too, as an address with no
  user name writes it (`query[:made-up@db.example:6379]` shows
  `query[:<hidden>@db.example:6379]`), but a colon written as `%3A` is part of the user name,
  as it is in an address, so `query[bob%3Amade-up@db.example]` shows as written. A password
  before a host that starts with a colon is hidden with no user before it
  (`query[::made-up@db.example:6379]` shows `query[:<hidden>@db.example:6379]`), but shows
  after a user, as a `::` joins the parts of a name: `query[bob::made-up@db.example:6379]`
  shows as written. A credential-like name glued to its value with a colon loses the value too
  (`query[token:made-up]` shows `query[token:<hidden>]`), also after another name, after the
  dash that joins two values and in quotes, as JSON writes a key
  (`query[5432-password:made-up]` shows `query[5432-password:<hidden>]`, and
  `query[{"token":"made-up"}]` shows `query[{"token":"<hidden>"}]`), but a whole number right
  after the slash that joins two parts of a name is a benchmark's named argument and shows
  (`BM_Hash/key:3`), and a double colon gives no value (`query[Token::Kind]`). Such a value ends where its part of the id ends, at a blank, a `/`, a
  `,`, a `;` or a bracket; after a scheme word such as Basic or Bearer, the token after the
  blank is hidden too (`query[--auth=Basic made-up]` shows `query[--auth=<hidden> <hidden>]`).
  The
  words in a pair of brackets, and the words of an id with no bracket, are read as the words
  of one argument of a command, so a client's password option
  (`bench[redis-cli -a made-up PING]` shows `bench[redis-cli -a <hidden> PING]`), a
  credential-like option written apart from its value (`query[--password made-up]` shows
  `query[--password <hidden>]`) and a header or a name before a colon that names a
  credential, which hides the rest of the words in its brackets
  (`bench[curl -H Authorization: Bearer made-up https://db.example/]` shows
  `bench[curl -H Authorization: <hidden>]`), lose their value; a program's text among them is
  read as the shown command reads it, so a credential's value it gives as a string is hidden
  (`bench[python -c "password = 'made-up'"]` shows
  `bench[python -c "password = '<hidden>'"]`). Words that stand outside the
  brackets of an id that has brackets are read only part by part, so
  `bench[x]/run --token made-up` shows as written. A host, with a
  scheme or without one, and a user show as the tool wrote them (`test_get[https://db.example/x]`,
  `BM_Connect/db.example:6379`, `test_login[bench@db.example]`). Two different ids of one launch
  that read the same once cut and hidden are refused with `E_USAGE`, never pooled into one case,
  when they differ only in a hidden secret (`query[token:made-up]` and
  `query[token:made-up-2]`), only in words that hold a `/` or in the folders of a path written
  with `%2F`, or only in both, and when they differ only in the spaces between the words a cut
  drops. When a cut drops a word that holds no `/`, the shown name ends with a mark, a space,
  `+` and eight hex digits made with a random key the run draws from the words of the id that
  hold no `/`, read with their secrets hidden: `query[/made/up/in.csv fast mode/x]` and `query[/made/up/in.csv slow mode/x]`
  show as `query[x]` with two marks, such as `query[x] +3c5e7a91` and `query[x] +b04d2f68`. A
  word that writes a `/` as `%2F`, such as `4%2Fq`, holds no `/`, and a path written with `%2F`
  from its start, with no letter, digit, `_`, `%`, `.`, `~` or `-` right before it, is cut to
  `%2F` and its last part wherever it stands, its folders read as folders; a blank ends it, as
  the limit on a folder name with a blank in such a path says. The private
  capture keeps the key and hashes of each id; the shared files hold neither. An id whose
  folders or secret alone differ from one launch or side to the next is read as the same case,
  and so are the ids of pooled captures that differ only in a folder or only in a secret, which
  a note names by the case. A mark is made with its run's key, so captures analysed apart can
  show one case with different marks: each new run and each new compare of result files draws
  a new key, a pool shows the marks of the first capture named, and `pairbench fill` refuses
  with exit 7 a document filled from one capture when it is filled from the results of another
  analysed apart. Pool the captures with one `pairbench compare`, or fill from the results of
  the same capture. A case that
  `hyperfine` names after its command is cleaned as the shown command is, but for the name of a
  home folder, which it keeps as any case id does
  (`curl https://db.example/x` gives `curl https://<hidden>/x`). A case id in rows given from
  outside, in the text input format or through the Python API, shows as written, an absolute
  path and a secret included (`t[/made/up/x.csv]`). Give a case that takes an address a name
  that holds none, as hyperfine's `--command-name` gives one.
- **A password before a host beside a credential in a case id.** In a part of a case id that
  also gives a credential-like name a value with `=` after the host, the value of that name is
  hidden and the password before the host shows:
  `test_db[bob:password@db.example:5432?sslmode=require&token=made-up]` shows
  `test_db[bob:password@db.example:5432?sslmode=require&token=<hidden>]`, and the password
  shows too where pytest joins such a name and its value to the host with `-`, as in
  `test_db[bob:password@db.example:5432-token=made-up]`.
- **A tag before a host in a case id.** A word after a `:`, with an `@` and a host that holds a
  dot or is followed by a port after it, is read as a password before a host, a tag or a version
  as much as a password, as an address with no user name writes one, so an image tag written
  that way is hidden: `test_tag[:latest@registry.example:5000]` shows
  `test_tag[:<hidden>@registry.example:5000]`, and so does
  `test_tag[:stable@registry.example:5000]`, so two such ids of one launch read the same and are
  refused with `E_USAGE`. Two such ids in different launches, or on different sides, are read as
  one case, as an id whose secret alone differs from one launch or side to the next is, so the
  rounds of both tags count toward one verdict. A name before the `:` is read as the user
  (`test_tag[app:latest@registry.example:5000]` shows
  `test_tag[app:<hidden>@registry.example:5000]`). Name such a case as an image reference
  writes it, the registry first (`test_tag[registry.example:5000/app:latest]`), or with no `@`
  and host after the tag (`test_tag[app:latest]`): written either way, `latest` and `stable`
  show as written and stay two cases while the image's name is not credential-like. A
  credential-like name glued to its value with `:` loses the value, an image's name too:
  `test_tag[auth:latest]` shows `test_tag[auth:<hidden>]`, and
  `test_tag[registry.example:5000/api-key:latest]` shows
  `test_tag[registry.example:5000/api-key:<hidden>]`, though a tag that is a whole number right
  after a `/` shows, as a benchmark's named argument does
  (`test_tag[registry.example:5000/api-key:3]`). Join the tag of such an image to its name with
  `-` (`test_tag[auth-latest]`), which shows as written.
- **A password that starts with a `:` before a host after a user in a case id.** A `::` joins
  the parts of a name, as in `test_dep[Module::Name@1.23]`, so a password before a host that
  starts with a `:` shows where a letter, a digit, `_`, `.`, `+`, `%` or `-` stands right
  before it, as a user or a value that pytest joins to it with `-` does:
  `test_db[bob::made-up@db.example:6379]` and `test_db[5432-::made-up@db.example:6379]` show as
  written. With nothing of that kind before it, such a password is hidden:
  `test_db[::made-up@db.example:6379]` shows `test_db[:<hidden>@db.example:6379]`. So is a name
  that starts with `::` before an `@` and a host or a version that holds a dot:
  `test_dep[::Name@1.23]` shows `test_dep[:<hidden>@1.23]`, so two such ids that differ only in
  that name are refused with `E_USAGE` in one launch and read as one case across launches or
  sides.
- **A password before a host written in another form in a case id.** A password before a host
  is hidden where the id writes it as `user:password@host`, with a host that holds a dot or is
  followed by a port right after the `@`. Written another way, it shows as written: with a `/`
  between the user and the password (`test_db[bob/made-up@db.example:1521/orcl]`), with the
  host in brackets (`test_db[bob:made-up@[::1]:6379]`), or with the host in a pair of
  parentheses after the name of a network (`test_db[bob:made-up@tcp(db.example:3306)/app]`).
- **A case pattern in the hash of the config.** The hash of the config, `config_sha256`, takes
  its case patterns, given with `--case` or as `cases.primary` or `cases.groups`, as typed. The
  shown command hides a credential in such a pattern, as `--case 'test_api[token:made-up]'`
  shows `--case 'test_api[token:<hidden>]'`, but someone who knows the rest of the config can
  confirm a guess at it by hashing the guess.

Give an address a host name it can have, put a space between two addresses, and write a
password word or a key apart from the word after it. Write a path with `/` and start it with
`/` rather than a variable, and in a shell text put quotes around the whole of a path whose
folder names hold a blank. Write a relative path that stays inside its folder without `..`
parts (`--path=lib:/made/up/lib` shows `--path=lib:lib`), give an address with two hosts or
more host names, none in brackets, and a port on the last host only, and write a credential in
the query of an address before any value that holds a `?`. In code, write a credential's value as one string on one line,
with nothing before its opening quote and no quote of its own inside it. Give a key to a side
through
`launch.env_pass` or a key file, and a Redis password with `-a` or `--pass`, or through
`launch.env_pass`. Write the command of a Redis client in a form the client reads, and give a
server its password on its command line (`--requirepass`) rather than in a file the side
writes. Write a client's option by its whole name, keep a client's password out of a comment,
and join nothing to a credential's value in code. Name a client by its own name where its
command starts, give a client the config
reference does not list its password with `--pass` or through `launch.env_pass`, give `ssh` its
remote command after the host, give the client of `--cluster call` its password with `-a`, and
write a client's option, command or password rule and the text of an `eval` in plain quotes
rather than in `$'...'` quotes. Write an option of `parallel` or `watch` glued to its
value (`-j2`, `--jobs=2`). In a case id, keep a password before a host out of a part that gives
a credential a value, write the colon before such a password as a colon rather than as
`%3A`, and write a case pattern as the results show the case
(`--case 'test_api[token:<hidden>]'`) or with a `*` in place of the secret
(`--case 'test_api*'`).

Where a program takes an address, write a host you do not want shown in one with a scheme
(`tool --url https://db.example:8080/v1` shows `tool --url 'https://<hidden>:8080/v1'`);
otherwise give it to the side in a variable that `launch.env_pass` names and write the
variable in the command (`sh -c 'tool -h "$DB_HOST"'` shows as typed).

## Known limits of the hashes

A published hash covers paths and hosts as typed, so a reader who knows the rest of a side's
command can confirm a guessed user name, host or path by hashing the guess. A side's
fingerprint covers its identity the same way, such as its command as typed and the output of
its `identify` command; of its executable it covers the last part of the path, not the folder.
To avoid it, keep such values out of the side's command: run it from a neutral folder, and pass
values to it through `launch.env_pass`, which no hash covers.

A file side's identity shows the SHA-256 of each result file the side reads, `files_sha256`,
taken over the file as it is, and its fingerprint covers those hashes and the absolute path of
each file. So a secret that a result file holds, such as a password in a case id that the
results show hidden, is in both hashes, and the same files in two folders give two
fingerprints: two exports that differ only in such a password give two values of
`files_sha256` and two fingerprints. A reader who has the rest of such a file can confirm a
guessed value by hashing the guess. Keep secrets out of the names a benchmark tool writes into
its result files, as hyperfine's `--command-name` gives a case a name of your choosing.

A line of an `identify` output that gives a name a version, two numbers or more joined by dots
after a colon and nothing else, is read as a package's version whatever the name, so
`DB_PASSWORD: 1.2.3` stays as printed in `identify_sha256`, in the side's fingerprint and in
`hash_inputs.json`. A reader who knows the rest of the output can confirm a guessed value by
hashing the guess, and a change to the value keeps captures made before and after it from
pooling (`E_POOL_SIDE_DRIFT`). Keep a password out of what an `identify` command prints, and
give it to the side through `launch.env_pass`.

The arguments of a serving side are read with the program that `serve.command` names; with no
`serve.command`, as for an image whose own entrypoint starts the server, they are read alone,
and an option that takes several keys, such as the `--api-key` of the vLLM server, is read as
one that takes one: of `serve.args = ["--model", "org/model-a", "--api-key", "KEY1", "KEY2"]`
the config's hash covers `KEY2` as typed. The hash of a serving side's arguments that its
identity holds reads them alone even when `serve.command` names the program. So a reader who
knows the rest of the side can confirm a guessed second key by hashing the guess. Give such a
server one key on its command line.

`tools/hash_inputs.py` of this repository writes `hash_inputs.json` into a run folder: the
values each published hash is taken over, rebuilt from the capture. It holds each side's whole
command with only the recognised secret forms hidden, so it is private like the capture: the
script writes it owner-only and says so on standard error, unless `results.json` and
`results.md` show every value it holds. A value passes only as one of these kinds, matched
exactly, never by its shape and never as a part of a longer value:

- **Shown values**: a whole value or key of `results.json`, or a whole word of one of its
  texts or keys or of a line of `results.md`; a published hash is such a value.
- **Neutral places**: the neutral places `/work`, `/home/user` and `/usr/local/bin/python3`.
  A neutral place passes only as itself; a path under one passes only when a shared file shows
  each of its other parts as a whole word. So a run made in `/work/made-up-folder/run`, or one
  whose command names a file in a folder of its own under `/home/user`, keeps its sidecar
  private as long as no shared file shows each of the path's other parts: the results show the
  last part of a path at most, but a case whose id is `made-up-folder run` shows both words and
  lets that path pass.
- **Schema ids and keys**: the sidecar's schema id, and a key that the sidecar, a side's
  identity, its launch or the config schema is written with, at the place it is written for;
  a key of a table whose keys the user names, such as a side's variables, is a value.
- **Config-schema values and config defaults**: a value that the config schema lists for its
  own key, and a config value equal to the tool's default at the same place.
- **Null, true, false and empty values**: an empty text, list or table included, none of which
  can name a place, a machine or a secret.

The shown command hides the value of each `--set`, so such a value passes only as another kind:
a memory cap such as `--set launch.memory=8g`, or any other `--set` value that is not a neutral
place, a listed value, a default or an empty value, keeps the sidecar private unless a shared
file shows that value in another place, such as the word `8g` in the workload's command.

Only such a sidecar may be shared: `--publish FOLDER` copies `results.json`, `results.md` and
`report.html` into the folder, and the sidecar with them only when it may be shared; otherwise
it keeps the sidecar owner-only in the run folder, says so on standard error and exits 0.
`--publish` refuses, with exit 2 and before it reads or writes any file, a `FOLDER` that is
empty, whose last part names no folder, such as `.`, or that is the run folder or a folder
inside it, through a link or not. It refuses the same way a `FOLDER` that holds the run folder,
at any depth, through a link or not, since the run's own private files would then lie inside the
published folder. It checks every file before it copies any: a publish that fails before its
first copy leaves `FOLDER` as it was and says "nothing published", and one that fails after it
says "partly published" and names exactly the files it copied, both with exit 2. A results file
kept in this repository has a sidecar that passed this check beside it, with one exception, in
`docs/figures/launch-cost/`: the launch-cost
results are kept without their sidecar because the results hide the two side commands; the
commands are the constants of `tools/launch_cost.py`, so a reader runs that script to repeat the
run rather than recomputing the hashes.
