# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential's value written as a string that a mark of its own opens is hidden whole.

In the text of a program the value given to a credential-like name may be a
string with a prefix (``f"..."``, ``rb'...'``, ``@"..."``, ``u8"..."``), a
raw string of Rust (``r#"..."#``), a quote-like word of Perl or a ``%`` word of
Ruby (``q{...}``, ``qq/.../``, ``%w[...]``), a pattern (``m/.../``, ``/.../``
after ``=~``), a substitution (``s/.../.../``), a string in backquotes, in
three quotes or in a here-document, or several strings joined by blanks,
``.`` or ``..``. It may also be compared with the name (``==``, ``!=``,
``===``, ``!==``, ``eq``, ``ne``, ``=~``, ``!~``). Each is hidden whole in
the shown command, and the hash is taken over it hidden, so two values give
one hash and no value can be confirmed from a published hash. The same text
inside a shell text, the remote command of ``ssh`` or an image's command is
hidden the same way. A string given to an ordinary name, and every word after
the hidden value, shows as typed and still tells two sides apart. Every value
is made up.
"""

from __future__ import annotations

import pytest

from pairbench import model
from pairbench.model import HIDDEN

# Two made-up values of one word, and one of several words, none a credential word.
VALUES = ("kiwi7mango42", "plum4grape19", "made kiwi7mango42 value")
# Each workload, ``{s}`` for the value, and the shown command, ``<hidden>`` for the hidden value.
HIDDEN_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "an f-string": (
        ("python3", "-c", 'token = f"{s}"; run_old()'),
        "python3 -c 'token = <hidden>; run_old()'",
    ),
    "a bytes string with r and b": (
        ("python3", "-c", "token = rb'{s}'; run_old()"),
        "python3 -c 'token = <hidden>; run_old()'",
    ),
    "a bytes string": (
        ("python3", "-c", 'password = b"{s}"; run_old()'),
        "python3 -c 'password = <hidden>; run_old()'",
    ),
    "two strings glued after = with no blank": (
        ("python3", "-c", 'API_KEY="made-up" "{s}";run_old()'),
        "python3 -c 'API_KEY=\"<hidden>\";run_old()'",
    ),
    "two strings joined by a blank": (
        ("python3", "-c", 'API_KEY = "made-up" "{s}"; run_old()'),
        "python3 -c 'API_KEY = \"<hidden>\"; run_old()'",
    ),
    "a Perl pattern with m after =~": (
        ("perl", "-e", "$token =~ m/{s}/ and run_old()"),
        "perl -e '$token =~ <hidden>'",
    ),
    "a Perl pattern after =~": (
        ("perl", "-e", "$password =~ /{s}/ and run_old()"),
        "perl -e '$password =~ <hidden>'",
    ),
    "a Perl q{} after eq": (
        ("perl", "-e", "if ($token eq q{{s}}) { run_old() }"),
        "perl -e 'if ($token eq <hidden>) { run_old() }'",
    ),
    "an f-string glued to =": (
        ("python3", "-c", 'token=f"{s}"; run_old()'),
        "python3 -c 'token=<hidden>; run_old()'",
    ),
    "an rb string glued to =": (
        ("python3", "-c", "token=rb'{s}'; run_old()"),
        "python3 -c 'token=<hidden>; run_old()'",
    ),
    "a b string glued to =": (
        ("python3", "-c", 'token=b"{s}"; run_old()'),
        "python3 -c 'token=<hidden>; run_old()'",
    ),
    "an r string glued to =": (
        ("python3", "-c", 'token=r"{s}"; run_old()'),
        "python3 -c 'token=<hidden>; run_old()'",
    ),
    "a u string glued to =": (
        ("python3", "-c", 'token=u"{s}"; run_old()'),
        "python3 -c 'token=<hidden>; run_old()'",
    ),
    "a Perl q{}": (
        ("perl", "-e", "$token = q{{s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl qq//": (
        ("perl", "-e", "$token = qq/{s}/; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl q()": (
        ("perl", "-e", "$token = q({s}); run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl qr//": (
        ("perl", "-e", "$token = qr/{s}/; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Ruby %q{}": (
        ("ruby", "-e", "token = %q{{s}}; run_old"),
        "ruby -e 'token = <hidden>; run_old'",
    ),
    "a JavaScript backquote string": (
        ("node", "-e", "const token = `{s}`; run_old()"),
        "node -e 'const token = <hidden>; run_old()'",
    ),
    "a Perl here-document": (
        ("perl", "-e", "my $token = <<EOT;\n{s}\nEOT\nrun_old();"),
        "perl -e 'my $token = <hidden>\nrun_old();'",
    ),
    "a Ruby here-document with ~": (
        ("ruby", "-e", "token = <<~EOS\n  {s}\n  EOS\nrun_old"),
        "ruby -e 'token = <hidden>\nrun_old'",
    ),
    "a Perl q{} after ne": (
        ("perl", "-e", "if ($token ne q{{s}}) { run_old() }"),
        "perl -e 'if ($token ne <hidden>) { run_old() }'",
    ),
    "a Perl m{} with a flag after !~": (
        ("perl", "-e", "$token !~ m{{s}}i and run_old()"),
        "perl -e '$token !~ <hidden>'",
    ),
    "a string after !=": (
        ("python3", "-c", 'if token != "{s}": run_old()'),
        "python3 -c 'if token != \"<hidden>\": run_old()'",
    ),
    "a string after ===": (
        ("node", "-e", 'if (token === "{s}") run_old()'),
        "node -e 'if (token === \"<hidden>\") run_old()'",
    ),
    "a string after !==": (
        ("node", "-e", 'if (token !== "{s}") run_old()'),
        "node -e 'if (token !== \"<hidden>\") run_old()'",
    ),
    "a string after ==": (
        ("python3", "-c", 'if token == "{s}": run_old()'),
        "python3 -c 'if token == \"<hidden>\": run_old()'",
    ),
    "a raw f-string in three quotes": (
        ("python3", "-c", 'API_KEY = fr"""{s}"""; run_old()'),
        "python3 -c 'API_KEY = <hidden>; run_old()'",
    ),
    "a raw bytes string in three quotes": (
        ("python3", "-c", "API_KEY = rb'''{s}'''; run_old()"),
        "python3 -c 'API_KEY = <hidden>; run_old()'",
    ),
    "a string in three quotes that holds quotes": (
        ("python3", "-c", 'API_KEY = """a "b" {s}"""; run_old()'),
        "python3 -c 'API_KEY = \"<hidden>\"; run_old()'",
    ),
    "two f-strings joined by a blank": (
        ("python3", "-c", 'API_KEY = f"made-up" f"{s}"; run_old()'),
        "python3 -c 'API_KEY = <hidden>; run_old()'",
    ),
    "an f-string joined to a string by a blank": (
        ("python3", "-c", 'API_KEY = "made-up" f"{s}"; run_old()'),
        "python3 -c 'API_KEY = \"<hidden>\"; run_old()'",
    ),
    "an f-string as a default": (
        ("python3", "-c", 'setdefault("HF_TOKEN", f"{s}"); run_old()'),
        "python3 -c 'setdefault(\"HF_TOKEN\", <hidden>); run_old()'",
    ),
    "a PHP here-document in double quotes": (
        ("php", "-r", '$api_key = <<<"EOT"\n{s}\nEOT;\nrun_old();'),
        "php -r '$api_key = <hidden>\nrun_old();'",
    ),
    "a PHP here-document in single quotes": (
        ("php", "-r", "$api_key = <<<'EOT'\n{s}\nEOT;\nrun_old();"),
        "php -r '$api_key = <hidden>\nrun_old();'",
    ),
    "a Perl here-document in single quotes": (
        ("perl", "-e", "my $api_key = <<'EOT';\n{s}\nEOT\nrun_old();"),
        "perl -e 'my $api_key = <hidden>\nrun_old();'",
    ),
    "a Perl here-document with ~": (
        ("perl", "-e", "my $api_key = <<~EOT;\n    {s}\n    EOT\nrun_old();"),
        "perl -e 'my $api_key = <hidden>\nrun_old();'",
    ),
    "a Ruby here-document with -": (
        ("ruby", "-e", "API_KEY = <<-EOS\n{s}\n  EOS\nrun_old"),
        "ruby -e 'API_KEY = <hidden>\nrun_old'",
    ),
    "a Ruby %w[]": (
        ("ruby", "-e", "API_KEY = %w[{s}]; run_old"),
        "ruby -e 'API_KEY = <hidden>; run_old'",
    ),
    "a Ruby %r{} with a flag": (
        ("ruby", "-e", "API_KEY = %r{{s}}i; run_old"),
        "ruby -e 'API_KEY = <hidden>; run_old'",
    ),
    "a Ruby %||": (
        ("ruby", "-e", "API_KEY = %|{s}|; run_old"),
        "ruby -e 'API_KEY = <hidden>; run_old'",
    ),
    "a Perl q~~": (
        ("perl", "-e", "$API_KEY = q~{s}~; run_old()"),
        "perl -e '$API_KEY = <hidden>; run_old()'",
    ),
    "a Perl qw//": (
        ("perl", "-e", "$API_KEY = qw/{s}/; run_old()"),
        "perl -e '$API_KEY = <hidden>; run_old()'",
    ),
    "a Perl q''": (
        ("perl", "-e", "$API_KEY = q'{s}'; run_old()"),
        "perl -e '$API_KEY = <hidden>; run_old()'",
    ),
    'a Perl qq""': (
        ("perl", "-e", '$API_KEY = qq"{s}"; run_old()'),
        "perl -e '$API_KEY = <hidden>; run_old()'",
    ),
    "a C# $@ string": (
        ("tool", "-e", 'var apiKey = $@"{s}"; RunOld();'),
        "tool -e 'var apiKey = <hidden>; RunOld();'",
    ),
    "a C# @$ string": (
        ("tool", "-e", 'var apiKey = @$"{s}"; RunOld();'),
        "tool -e 'var apiKey = <hidden>; RunOld();'",
    ),
    "a Rust raw bytes string": (
        ("tool", "-e", 'let api_key = br#"{s}"#; run_old();'),
        "tool -e 'let api_key = <hidden>; run_old();'",
    ),
    "a Rust raw string with two #": (
        ("tool", "-e", 'let api_key = r##"{s} "# x"##; run_old();'),
        "tool -e 'let api_key = <hidden>; run_old();'",
    ),
    "a C++ u8 string": (
        ("tool", "-e", 'auto api_key = u8"{s}"; run_old();'),
        "tool -e 'auto api_key = <hidden>; run_old();'",
    ),
    "a C++ L string": (
        ("tool", "-e", 'auto api_key = L"{s}"; run_old();'),
        "tool -e 'auto api_key = <hidden>; run_old();'",
    ),
    "two PHP strings joined by .": (
        ("php", "-r", '$api_key = "made-up" . "{s}"; run_old();'),
        "php -r '$api_key = \"<hidden>\"; run_old();'",
    ),
    "two Lua strings joined by ..": (
        ("lua", "-e", 'api_key = "made-up" .. "{s}"; run_old()'),
        "lua -e 'api_key = \"<hidden>\"; run_old()'",
    ),
    "an f-string in brackets": (
        ("python3", "-c", 'print(1); API_KEY = (f"{s}"); run_old()'),
        "python3 -c 'print(1); API_KEY = <hidden>; run_old()'",
    ),
    "an f-string before if": (
        ("python3", "-c", 'API_KEY = f"{s}" if x else "y"; run_old()'),
        "python3 -c 'API_KEY = <hidden>; run_old()'",
    ),
    "an f-string in a shell text": (
        ("sh", "-c", "python3 -c 'token = f\"{s}\"; run_old()'"),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "an rb string in double quotes in a shell text": (
        ("sh", "-c", "python3 -c \"token = rb'{s}'; run_old()\""),
        "sh -c 'python3 -c \"token = <hidden>; run_old()\"'",
    ),
    "a Perl pattern in a shell text": (
        ("sh", "-c", "perl -e '$token =~ m/{s}/ and run_old()'"),
        "sh -c 'perl -e '\"'\"'$token =~ <hidden>'\"'\"''",
    ),
    "two strings in a shell text after bash -lc": (
        ("bash", "-lc", 'python3 -c \'API_KEY = "made-up" "{s}"; run_old()\''),
        "bash -lc 'python3 -c '\"'\"'API_KEY = \"<hidden>\"; run_old()'\"'\"''",
    ),
    "an f-string in the remote command of ssh": (
        ("ssh", "made-up-host", "python3 -c 'token = f\"{s}\"; run_old()'"),
        "ssh made-up-host 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "an f-string after env -S": (
        ("env", "-S", "python3 -c 'token = f\"{s}\"; run_old()'"),
        "env -S 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "an f-string in an image's command": (
        ("docker", "run", "img", "python3", "-c", 'token = f"{s}"; run_old()'),
        "docker run img python3 -c 'token = <hidden>; run_old()'",
    ),
    "an f-string in single quotes": (
        ("python3", "-c", "token = f'{s}'; run_old()"),
        "python3 -c 'token = <hidden>; run_old()'",
    ),
    "an f-string given to a keyword": (
        ("python3", "-c", 'connect(password=f"{s}", host="db")'),
        "python3 -c 'connect(password=<hidden> host=\"db\")'",
    ),
    "an f-string in a dictionary": (
        ("python3", "-c", 'd = {"api_key": f"{s}", "n": 1}; run_old(d)'),
        'python3 -c \'d = {"api_key": <hidden>, "n": 1}; run_old(d)\'',
    ),
    "a Perl substitution after =~": (
        ("perl", "-e", "$token =~ s/{s}/x/ and run_old()"),
        "perl -e '$token =~ <hidden>'",
    ),
    "a Perl substitution in braces": (
        ("perl", "-e", "$token =~ s{{s}}{x}; run_old()"),
        "perl -e '$token =~ <hidden>; run_old()'",
    ),
    "a Perl substitution in braces with a blank between its parts": (
        ("perl", "-e", "$token =~ s{{s}} {x}; run_old()"),
        "perl -e '$token =~ <hidden>; run_old()'",
    ),
    "a Perl tr///": (
        ("perl", "-e", "$token =~ tr/{s}/x/; run_old()"),
        "perl -e '$token =~ <hidden>; run_old()'",
    ),
    "a Perl y///": (
        ("perl", "-e", "$token =~ y/{s}/x/; run_old()"),
        "perl -e '$token =~ <hidden>; run_old()'",
    ),
    "a Perl qq// in a shell text before an operator": (
        ("sh", "-c", "perl -e '$token = qq/{s}/; print 1' && true"),
        "sh -c 'perl -e '\"'\"'$token = <hidden>; print 1'\"'\"' && true'",
    ),
    "a Perl q{} in a shell text after a quoted word": (
        ("sh", "-c", "echo 'x' && perl -e '$token = q{{s}}; print 1'"),
        "sh -c 'echo '\"'\"'x'\"'\"' && perl -e '\"'\"'$token = <hidden>; print 1'\"'\"''",
    ),
    "a Ruby here-document in a shell text": (
        ("sh", "-c", "ruby -e 'token = <<~EOS\n  {s}\n  EOS\nrun_old'"),
        "sh -c 'ruby -e '\"'\"'token = <hidden>\nrun_old'\"'\"''",
    ),
    "a pattern with a blank after =~ in a nested shell text": (
        ("sh", "-c", "bash -c '[[ $TOKEN =~ /made {s}/ ]] && run'"),
        "sh -c 'bash -c '\"'\"'[[ $TOKEN =~ <hidden> ]] && run'\"'\"''",
    ),
    "a Perl q with an escaped slash and a blank": (
        ("perl", "-e", "$token = q/made\\/ {s}/; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl qq in bars with an escaped bar and a blank": (
        ("perl", "-e", "$token = qq|made\\| {s}|; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl q in braces with braces inside": (
        ("perl", "-e", "$token = q{made {x} {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "an f-string written apart from its prefix in a shell text": (
        ("sh", "-c", "python3 -c 'token = f'\"'\"'{s}'\"'\"'; run_old()'"),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "an rb string with a blank written apart from its prefix in a shell text": (
        ("sh", "-c", "python3 -c 'token = rb'\"'\"'made {s}'\"'\"'; run_old()'"),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "two prefixed strings in single quotes in a shell text": (
        ("sh", "-c", "python3 -c \"token = rb'made' b'{s}'; run_old()\""),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "two prefixed strings in double quotes in a shell text": (
        ("sh", "-c", 'python3 -c \'token = rb"made" b"{s}"; run_old()\''),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "a Perl pattern with a blank before its end in a shell text": (
        ("sh", "-c", "perl -e '$token =~ /made {s} / and run_old()'"),
        "sh -c 'perl -e '\"'\"'$token =~ <hidden>'\"'\"''",
    ),
    "a Perl q in slashes with a blank before its end in a shell text": (
        ("sh", "-c", "perl -e '$token = q/made {s} /; run_old()'"),
        "sh -c 'perl -e '\"'\"'$token = <hidden>; run_old()'\"'\"''",
    ),
    "a Perl m with a flag and a blank before its end in a shell text": (
        ("sh", "-c", "perl -e '$token =~ m/made {s} /x; run_old()'"),
        "sh -c 'perl -e '\"'\"'$token =~ <hidden>; run_old()'\"'\"''",
    ),
    "a Perl q in slashes glued to a variable in a shell text": (
        ("sh", "-c", "perl -e '$token=q/made {s} /'"),
        "sh -c 'perl -e '\"'\"'$token=<hidden>'\"'\"''",
    ),
    "a Perl q in slashes after a key in braces in a shell text": (
        ("sh", "-c", "perl -e '$ENV{TOKEN}=q/made {s} /'"),
        "sh -c 'perl -e '\"'\"'$ENV{TOKEN}=<hidden>'\"'\"''",
    ),
    "a Perl pattern after != in a shell text": (
        ("sh", "-c", "perl -e 'print if token!=/made {s} /'"),
        "sh -c 'perl -e '\"'\"'print if token!=<hidden>'\"'\"''",
    ),
    "a Perl pattern after == in double quotes in a shell text": (
        ("sh", "-c", 'perl -e "\\$x if token==/made {s} /; run_old()"'),
        "sh -c 'perl -e \"\\$x if token=<hidden>; run_old()\"'",
    ),
    "a Perl q in slashes in a here-document of a shell text": (
        ("sh", "-c", "perl <<'END'\n$token = q/made {s} /;\nrun_old();\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"'\n$token = <hidden>;\nrun_old();\nEND'",
    ),
    "a Perl qq in bars in an unquoted here-document": (
        ("sh", "-c", "perl <<END\n$token = qq|made {s} |;\nrun_old();\nEND"),
        "sh -c 'perl <<END\n$token = <hidden>;\nrun_old();\nEND'",
    ),
    "a Perl pattern after =~ in a here-document": (
        ("sh", "-c", "perl <<'END'\n$token =~ /made {s} / and run_old();\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"'\n$token =~ <hidden>;\nEND'",
    ),
    "two Perl strings joined by . in a here-document": (
        ("sh", "-c", "perl <<'END'\n$token = 'made' . '{s}';\nrun_old();\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"'\n$token = '\"'\"'<hidden>'\"'\"';\nrun_old();\nEND'",
    ),
    "a Perl here-document in a here-document": (
        ("sh", "-c", "perl <<'END'\n$token = <<EOT;\nmade {s}\nEOT\nrun_old();\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"'\n$token = <hidden>\nrun_old();\nEND'",
    ),
    "an f-string in a here-document": (
        ("sh", "-c", "python3 <<'END'\ntoken = f'made {s}'\nrun_old()\nEND"),
        "sh -c 'python3 <<'\"'\"'END'\"'\"'\ntoken = <hidden>\nrun_old()\nEND'",
    ),
    "an rb string in an unquoted here-document": (
        ("sh", "-c", "python3 <<END\ntoken = rb'made {s}'\nrun_old()\nEND"),
        "sh -c 'python3 <<END\ntoken = <hidden>\nrun_old()\nEND'",
    ),
    "two strings joined by a blank in a here-document": (
        ("sh", "-c", "python3 <<'END'\ntoken = 'made' '{s}'\nrun_old()\nEND"),
        "sh -c 'python3 <<'\"'\"'END'\"'\"'\ntoken = '\"'\"'<hidden>'\"'\"'\nrun_old()\nEND'",
    ),
    "a Ruby here-document in a here-document": (
        ("sh", "-c", "ruby <<'END'\ntoken = <<~EOT\n  made {s}\nEOT\nrun_old\nEND"),
        "sh -c 'ruby <<'\"'\"'END'\"'\"'\ntoken = <hidden>\nrun_old\nEND'",
    ),
    "a Ruby pattern in a here-document": (
        ("sh", "-c", "ruby <<'END'\ntoken = /made {s} /\nrun_old\nEND"),
        "sh -c 'ruby <<'\"'\"'END'\"'\"'\ntoken = <hidden>\nrun_old\nEND'",
    ),
    "a string in backquotes in a here-document": (
        ("sh", "-c", "node <<'END'\ntoken = `made {s}`;\nrunOld();\nEND"),
        "sh -c 'node <<'\"'\"'END'\"'\"'\ntoken = <hidden>;\nrunOld();\nEND'",
    ),
    "a pattern of node in a here-document": (
        ("sh", "-c", "node <<'END'\ntoken = /made {s} /;\nrunOld();\nEND"),
        "sh -c 'node <<'\"'\"'END'\"'\"'\ntoken = <hidden>;\nrunOld();\nEND'",
    ),
    "a PHP here-document in a here-document": (
        ("sh", "-c", "php <<'END'\n$token = <<<EOT\nmade {s}\nEOT;\nrun_old();\nEND"),
        "sh -c 'php <<'\"'\"'END'\"'\"'\n$token = <hidden>\nrun_old();\nEND'",
    ),
    "a Perl q in a here-document of the remote command of ssh": (
        ("ssh", "made-up-host", "perl <<'END'\n$token = q/made {s} /;\nEND"),
        "ssh made-up-host 'perl <<'\"'\"'END'\"'\"'\n$token = <hidden>;\nEND'",
    ),
    "an f-string in a here-document with tabs": (
        ("sh", "-c", "python3 <<-'END'\n\ttoken = f'made {s}'\n\tEND"),
        "sh -c 'python3 <<-'\"'\"'END'\"'\"'\n\ttoken = <hidden>\n\tEND'",
    ),
    "a Perl q with a mark that is no bracket": (
        ("perl", "-e", "$token = q%made {s}%; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl qq closed by a semicolon": (
        ("perl", "-e", "$password = qq;made {s};; run_old()"),
        "perl -e '$password = <hidden>; run_old()'",
    ),
    "a Perl q with a comma": (
        ("perl", "-e", "$token = q,made {s},; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl q with a blank before its brace": (
        ("perl", "-e", "$token = q {made {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl qq with a blank before its slash": (
        ("perl", "-e", "$token = qq /made {s}/; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl m with a mark that is no bracket": (
        ("perl", "-e", "$token =~ m%made {s}% and run_old()"),
        "perl -e '$token =~ <hidden>'",
    ),
    "a Perl q with a caret compared with eq": (
        ("perl", "-e", "if ($token eq q^made {s}^) { run_old() }"),
        "perl -e 'if ($token eq <hidden>) { run_old() }'",
    ),
    "a Perl q with an at sign given to a key of a hash": (
        ("perl", "-e", "$ENV{TOKEN} = q@made {s}@; run_old()"),
        "perl -e '$ENV{TOKEN} = <hidden>; run_old()'",
    ),
    "a string joined to a Perl q": (
        ("perl", "-e", "$token = q{a} . 'made {s}'; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl q joined to a string": (
        ("perl", "-e", "$token = 'a' . q{made {s}}; run_old()"),
        "perl -e '$token = '\"'\"'<hidden>; run_old()'",
    ),
    "two Perl q joined with no blank": (
        ("perl", "-e", "$token = q{a}.q{made {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a string joined to a Perl qq with a slash": (
        ("perl", "-e", '$token = qq/a/ . "made {s}"; run_old()'),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a string after a Ruby %q": (
        ("ruby", "-e", "token = %q{a} 'made {s}'; run_old"),
        "ruby -e 'token = <hidden>; run_old'",
    ),
    "a here-document whose end word has a backslash in a shell text": (
        ("sh", "-c", "python3 <<\\END\ntoken = f'made {s}'\nrun_old()\nEND"),
        "sh -c 'python3 <<\\END\ntoken = <hidden>\nrun_old()\nEND'",
    ),
    "a Perl here-document whose end word has a backslash": (
        ("perl", "-e", "my $token = <<\\EOT;\nmade {s}\nEOT\nrun_old();"),
        "perl -e 'my $token = <hidden>\nrun_old();'",
    ),
    "a Perl string joined with a dot at the end of a line": (
        ("perl", "-e", "my $token = 'made' .\n  '{s}'; run_old()"),
        "perl -e 'my $token = '\"'\"'<hidden>'\"'\"'; run_old()'",
    ),
    "a Perl string joined with a dot at the start of a line": (
        ("perl", "-e", "my $token = 'made'\n  . '{s}'; run_old()"),
        "perl -e 'my $token = '\"'\"'<hidden>'\"'\"'; run_old()'",
    ),
    "a Python string carried on with a backslash": (
        ("python3", "-c", "token = 'made ' \\\n  '{s}'\nrun_old()"),
        "python3 -c 'token = '\"'\"'<hidden>'\"'\"'\nrun_old()'",
    ),
    "a Python sum carried on with a backslash": (
        ("python3", "-c", "token = 'made ' + \\\n  '{s}'\nrun_old()"),
        "python3 -c 'token = '\"'\"'<hidden>'\"'\"'\nrun_old()'",
    ),
    "a JavaScript sum at the end of a line": (
        ("node", "-e", "const token = 'made ' +\n  '{s}';\nrun_old()"),
        "node -e 'const token = '\"'\"'<hidden>'\"'\"';\nrun_old()'",
    ),
    "a Ruby string carried on with a backslash": (
        ("ruby", "-e", 'token = "made" \\\n  "{s}"\nrun_old'),
        "ruby -e 'token = \"<hidden>\"\nrun_old'",
    ),
    "a Perl string joined across a line in a here-document": (
        ("sh", "-c", "perl <<'END'\nmy $token = 'made' .\n  '{s}';\nrun_old();\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"'\nmy $token = '\"'\"'<hidden>'\"'\"';\nrun_old();\nEND'",
    ),
    "a Perl quote-like word joined across a line": (
        ("perl", "-e", "$token = q{made} .\n  '{s}'; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "an f-string with escaped quotes in double quotes in a shell text": (
        ("sh", "-c", 'python3 -c "token = f\\"made {s}\\"; run_old()"'),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "a byte string with escaped quotes in double quotes in a shell text": (
        ("sh", "-c", 'python3 -c "token = rb\\"made {s}\\"; run_old()"'),
        "sh -c 'python3 -c '\"'\"'token = <hidden>; run_old()'\"'\"''",
    ),
    "a Perl variable between two joined strings": (
        ("perl", "-e", "$token = 'made' . $x . ' {s}'; run_old()"),
        "perl -e '$token = '\"'\"'<hidden>'\"'\"'; run_old()'",
    ),
    "a Perl variable glued between two joined strings": (
        ("perl", "-e", "$token = 'made'.$x.'{s}'; run_old()"),
        "perl -e '$token = '\"'\"'<hidden>'\"'\"'; run_old()'",
    ),
    "a PHP variable between two joined strings": (
        ("php", "-r", "$token = 'made' . $x . ' {s}'; run_old();"),
        "php -r '$token = '\"'\"'<hidden>'\"'\"'; run_old();'",
    ),
    "a string joined to a Perl variable": (
        ("perl", "-e", "$token = $x . ' {s}'; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl quote-like word over two lines": (
        ("perl", "-e", "$token = q/made\n{s}/; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a Perl quote-like word over two lines in a shell text": (
        ("sh", "-c", "perl -e '$token = qq|made\n{s}|; run_old()'"),
        "sh -c 'perl -e '\"'\"'$token = <hidden>; run_old()'\"'\"''",
    ),
}
# Each ordinary workload, ``{s}`` for a value that shows, and its shown command.
SHOWN_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "an f-string given to an ordinary name": (
        ("python3", "-c", 'NAME = f"{s}"; run_old()'),
        "python3 -c 'NAME = f\"{s}\"; run_old()'",
    ),
    "an rb string given to an ordinary name": (
        ("python3", "-c", "DATA = rb'{s}'; run_old()"),
        "python3 -c 'DATA = rb'\"'\"'{s}'\"'\"'; run_old()'",
    ),
    "two strings given to an ordinary name": (
        ("python3", "-c", 'LABEL = "made-up" "{s}"; run_old()'),
        'python3 -c \'LABEL = "made-up" "{s}"; run_old()\'',
    ),
    "a Perl q{} given to an ordinary name": (
        ("perl", "-e", "$name = q{{s}}; run_old()"),
        "perl -e '$name = q{{s}}; run_old()'",
    ),
    "a Perl qr// given to an ordinary name": (
        ("perl", "-e", "$re = qr/{s}/; run_old()"),
        "perl -e '$re = qr/{s}/; run_old()'",
    ),
    "a shell here-document": (
        ("sh", "-c", "cat <<EOF\nlabel={s}\nEOF"),
        "sh -c 'cat <<EOF\nlabel={s}\nEOF'",
    ),
    "a Ruby %q{} given to an ordinary name": (
        ("ruby", "-e", "name = %q{{s}}; run_old"),
        "ruby -e 'name = %q{{s}}; run_old'",
    ),
    "a Perl q{} compared with an ordinary name": (
        ("perl", "-e", "if ($name eq q{{s}}) { run_old() }"),
        "perl -e 'if ($name eq q{{s}}) { run_old() }'",
    ),
    "a Perl pattern matched against an ordinary name": (
        ("perl", "-e", "$label =~ m/{s}/ and run_old()"),
        "perl -e '$label =~ m/{s}/ and run_old()'",
    ),
    "a string compared with an ordinary name": (
        ("python3", "-c", 'if name == "{s}": run_old()'),
        "python3 -c 'if name == \"{s}\": run_old()'",
    ),
    "an f-string printed": (
        ("python3", "-c", 'print(f"hello {x} {s}"); run_old()'),
        "python3 -c 'print(f\"hello {x} {s}\"); run_old()'",
    ),
    "a string in three quotes": (
        ("python3", "-c", 'msg = """{s} text"""; print(msg)'),
        'python3 -c \'msg = """{s} text"""; print(msg)\'',
    ),
    "two strings joined by a blank": (
        ("python3", "-c", 'msg = "made" "{s}"; print(msg)'),
        'python3 -c \'msg = "made" "{s}"; print(msg)\'',
    ),
    "two Perl strings joined by .": (
        ("perl", "-e", '$msg = "made" . "{s}"; print $msg'),
        'perl -e \'$msg = "made" . "{s}"; print $msg\'',
    ),
    "a Perl m{} pattern on its own": (
        ("perl", "-ne", "print if m{{s}}"),
        "perl -ne 'print if m{{s}}'",
    ),
    "a pattern of grep": (
        ("grep", "-E", "{s}|other", "in.txt"),
        "grep -E '{s}|other' in.txt",
    ),
    "a substitution of sed": (
        ("sed", "-e", "s/{s}/text/"),
        "sed -e s/{s}/text/",
    ),
    "a backquote string given to an ordinary name": (
        ("node", "-e", "const msg = `{s}`; run_old()"),
        "node -e 'const msg = `{s}`; run_old()'",
    ),
    "a PHP here-document": (
        ("php", "-r", "$msg = <<<EOT\n{s}\nEOT;\nrun_old();"),
        "php -r '$msg = <<<EOT\n{s}\nEOT;\nrun_old();'",
    ),
    "a shell word after a quoted credential value": (
        ("sh", "-c", 'API_KEY="made-up" "./bench-{s}"'),
        "sh -c 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a bare shell word after a quoted credential value": (
        ("sh", "-c", 'API_KEY="made-up" ./bench-{s}'),
        "sh -c 'API_KEY=<hidden> ./bench-{s}'",
    ),
    "a call after a division": (
        ("python3", "-c", "token = m/2; run_{s}()"),
        "python3 -c 'token = <hidden>; run_{s}()'",
    ),
    "a call after a method call": (
        ("python3", "-c", "token = q.get(); run_{s}()"),
        "python3 -c 'token = <hidden>; run_{s}()'",
    ),
    "a line after a credential's line": (
        ("python3", "-c", 'token = "made-up"\nprint("{s}")'),
        'python3 -c \'token = "<hidden>"\nprint("{s}")\'',
    ),
    "a statement after a credential's statement": (
        ("python3", "-c", 'token = "made-up"; print("{s}")'),
        'python3 -c \'token = "<hidden>"; print("{s}")\'',
    ),
    "a second item after a credential's string": (
        ("python3", "-c", 'token = "made-up", "{s}"'),
        'python3 -c \'token = "<hidden>", "{s}"\'',
    ),
    "a string compared with a name that holds a credential word inside": (
        ("perl", "-e", '$frequent eq "{s}" and run_old()'),
        "perl -e '$frequent eq \"{s}\" and run_old()'",
    ),
    "a shell test of an ordinary variable": (
        ("sh", "-c", '[ "$token_count" -eq 5 ] && echo {s}'),
        "sh -c '[ \"$token_count\" -eq 5 ] && echo {s}'",
    ),
    "a print after a test of a credential": (
        ("python3", "-c", 'if token: print("{s}")'),
        "python3 -c 'if token: print(\"{s}\")'",
    ),
    "a print after a here-document given to a credential": (
        ("perl", "-e", 'my $api_key = <<EOT;\nmade-up\nEOT\nprint "{s}";'),
        "perl -e 'my $api_key = <hidden>\nprint \"{s}\";'",
    ),
    "a comment after a credential's string": (
        ("python3", "-c", 'token = "made-up" # "{s}"'),
        'python3 -c \'token = "<hidden>" # "{s}"\'',
    ),
    "a print after a default": (
        ("python3", "-c", 'password = get() or "made-up"; print("{s}")'),
        "python3 -c 'password = <hidden>; print(\"{s}\")'",
    ),
    "a word after env's assignment": (
        ("env", "API_KEY=made-up", "./bench-{s}"),
        "env 'API_KEY=<hidden>' ./bench-{s}",
    ),
    "a shell word after a prefixed value": (
        ("sh", "-c", 'API_KEY=f"made-up" ./bench-{s}'),
        "sh -c 'API_KEY=<hidden> ./bench-{s}'",
    ),
    "a shell word after strings joined by .": (
        ("sh", "-c", 'API_KEY="a"."b" ./bench-{s}'),
        "sh -c ''\"'\"'API_KEY=<hidden>'\"'\"' ./bench-{s}'",
    ),
    "a word of a shell text after watch": (
        ("watch", 'API_KEY="made-up" "./bench-{s}"'),
        "watch 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a word of the remote command of ssh": (
        ("ssh", "made-up-host", 'API_KEY="made-up" "./bench-{s}"'),
        "ssh made-up-host 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a word of a shell text after env -S": (
        ("env", "-S", 'API_KEY="made-up" "./bench-{s}"'),
        "env -S 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a word of a shell text after timeout": (
        ("timeout", "5", "sh", "-c", 'API_KEY="made-up" "./bench-{s}"'),
        "timeout 5 sh -c 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a word of a shell text after parallel": (
        ("parallel", 'API_KEY="made-up" "./bench-{s}"', ":::", "1"),
        "parallel 'API_KEY=<hidden> \"./bench-{s}\"' ::: 1",
    ),
    "a word of a shell text after tmux": (
        ("tmux", "new", 'API_KEY="made-up" "./bench-{s}"'),
        "tmux new 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a word of a shell text after su -c": (
        ("su", "-c", 'API_KEY="made-up" "./bench-{s}"'),
        "su -c 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a word of a shell text after script -c": (
        ("script", "-c", 'API_KEY="made-up" "./bench-{s}"'),
        "script -c 'API_KEY=<hidden> \"./bench-{s}\"'",
    ),
    "a joined string on a later line": (
        ("python3", "-c", 'token = "made-up"\nx = "a" "{s}"'),
        'python3 -c \'token = "<hidden>"\nx = "a" "{s}"\'',
    ),
    "a path after a value that starts as a Perl pattern in a shell text": (
        ("sh", "-c", "TOKEN=m/made ./run-{s}/b"),
        "sh -c 'TOKEN=<hidden> ./run-{s}/b'",
    ),
    "a word after a value that starts with a slash in a shell text": (
        ("sh", "-c", "API_KEY=/made {s} --out=/x"),
        "sh -c 'API_KEY=<hidden> {s} --out=x'",
    ),
    "an address after a value that starts with a slash in a shell text": (
        ("sh", "-c", "API_KEY=/made {s} http://localhost/x"),
        "sh -c 'API_KEY=<hidden> {s} http://localhost/x'",
    ),
    "a home path after a value of q in a shell text": (
        ("sh", "-c", "API_KEY=q/made ~/x/{s}"),
        "sh -c 'API_KEY=<hidden> {s}'",
    ),
    "a parent path after a value of m in a shell text": (
        ("sh", "-c", "API_KEY=m/made ../x/{s}"),
        "sh -c 'API_KEY=<hidden> {s}'",
    ),
    "a word after a value that starts as a Perl q{ outside quotes": (
        ("sh", "-c", "echo 'x'; API_KEY=q{made {s}"),
        "sh -c 'echo '\"'\"'x'\"'\"'; API_KEY=<hidden> {s}'",
    ),
    "a word after a value in slashes in a nested shell text": (
        ("sh", "-c", "bash -c 'API_KEY=/made {s}/x && run'"),
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden> {s}/x && run'\"'\"''",
    ),
    "a home path after a value of q in a nested shell text": (
        ("sh", "-c", "bash -c 'API_KEY=q/made ~/x/{s}'"),
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden> {s}'\"'\"''",
    ),
    "a path after a value of m in a nested shell text": (
        ("sh", "-c", "bash -c 'API_KEY=m/made ./run-{s}/b'"),
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden> ./run-{s}/b'\"'\"''",
    ),
    "an option's path after a value of q in a nested shell text": (
        ("sh", "-c", "bash -c 'API_KEY=q/made --out=/x/{s}'"),
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden> --out={s}'\"'\"''",
    ),
    "an address after a value of q in a nested shell text": (
        ("sh", "-c", "bash -c 'API_KEY=q/made http://x/{s}'"),
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden> http://<hidden>/{s}'\"'\"''",
    ),
    "a parent path after a value of q in a nested shell text": (
        ("sh", "-c", "bash -c 'API_KEY=q/made ../x/{s}'"),
        "sh -c 'bash -c '\"'\"'API_KEY=<hidden> {s}'\"'\"''",
    ),
    "an f-string with no credential in a here-document": (
        ("sh", "-c", "python3 <<'END'\nprint(f'made {s}')\nEND"),
        "sh -c 'python3 <<'\"'\"'END'\"'\"'\nprint(f'\"'\"'made {s}'\"'\"')\nEND'",
    ),
    "a path after a value in a here-document": (
        ("sh", "-c", "bash <<'END'\nAPI_KEY=/made/x ./run-{s}\nEND"),
        "sh -c 'bash <<'\"'\"'END'\"'\"'\nAPI_KEY=<hidden> ./run-{s}\nEND'",
    ),
    "a Perl q given to an ordinary name in a here-document": (
        ("sh", "-c", "perl <<'END'\nmy $name = q/made {s}/; run_old();\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"'\nmy $name = q/made {s}/; run_old();\nEND'",
    ),
    "the words after a here-document": (
        ("sh", "-c", "perl <<'END' && ./run-{s}\n$token = q/made/;\nEND"),
        "sh -c 'perl <<'\"'\"'END'\"'\"' && ./run-{s}\n$token = <hidden>;\nEND'",
    ),
    "a Perl pattern glued to a variable in a nested shell text": (
        ("sh", "-c", "bash -c '$token=/made {s} / && run'"),
        "sh -c 'bash -c '\"'\"'$token=<hidden> {s} / && run'\"'\"''",
    ),
    "a q, an m and an f-string given to no name in a file's here-document": (
        (
            "sh",
            "-c",
            "cat > notes.txt <<'END'\nsee q{made {s}} and m|made {s}| and f'made {s}'\nEND",
        ),
        "sh -c 'cat > notes.txt <<'\"'\"'END'\"'\"'\n"
        "see q{made {s}} and m|made {s}| and f'\"'\"'made {s}'\"'\"'\nEND'",
    ),
    "a pattern in a sed before a here-document": (
        ("sh", "-c", "sed -e 's|made|{s}|' <<'END'\nx\nEND"),
        "sh -c 'sed -e '\"'\"'s|made|{s}|'\"'\"' <<'\"'\"'END'\"'\"'\nx\nEND'",
    ),
    "a Perl q with a percent sign given to an ordinary name": (
        ("perl", "-e", "$name = q%made {s}%; run_old()"),
        "perl -e '$name = q%made {s}%; run_old()'",
    ),
    "a Perl m with a percent sign matched against an ordinary name": (
        ("perl", "-e", "$label =~ m%made {s}% and run_old()"),
        "perl -e '$label =~ m%made {s}% and run_old()'",
    ),
    "a string joined to a Perl q given to an ordinary name": (
        ("perl", "-e", "$name = q{a} . 'made {s}'; run_old()"),
        "perl -e '$name = q{a} . '\"'\"'made {s}'\"'\"'; run_old()'",
    ),
    "a value of q and a dot given to a name of Python": (
        ("python3", "-c", "token = q.get(); name = a.b('{s}')"),
        "python3 -c 'token = <hidden>; name = a.b('\"'\"'{s}'\"'\"')'",
    ),
    "a Perl q before a fat comma": (
        ("perl", "-e", "%h = (q => '{s}'); run_old()"),
        "perl -e '%h = (q => '\"'\"'{s}'\"'\"'); run_old()'",
    ),
    "a here-document whose end word has a backslash and no credential": (
        ("sh", "-c", "python3 <<\\END\nlabel = f'made {s}'\nEND"),
        "sh -c 'python3 <<\\END\nlabel = f'\"'\"'made {s}'\"'\"'\nEND'",
    ),
    "a string on the next line with no join after a credential": (
        ("python3", "-c", "token = 'x'\nlabel = '{s}'\nrun_old()"),
        "python3 -c 'token = '\"'\"'<hidden>'\"'\"'\nlabel = '\"'\"'{s}'\"'\"'\nrun_old()'",
    ),
    "a bare string on the next line after a credential": (
        ("python3", "-c", "token = 'x'\n'{s}'\nrun_old()"),
        "python3 -c 'token = '\"'\"'<hidden>'\"'\"'\n'\"'\"'{s}'\"'\"'\nrun_old()'",
    ),
    "a Perl join across a line given to an ordinary name": (
        ("perl", "-e", "my $label = 'made' .\n  '{s}'; run_old()"),
        "perl -e 'my $label = '\"'\"'made'\"'\"' .\n  '\"'\"'{s}'\"'\"'; run_old()'",
    ),
    "an f-string with escaped quotes given to an ordinary name": (
        ("sh", "-c", 'python3 -c "label = f\\"made {s}\\"; run_old()"'),
        'sh -c \'python3 -c "label = f\\"made {s}\\"; run_old()"\'',
    ),
    "a Perl variable between joined strings given to an ordinary name": (
        ("perl", "-e", "$label = 'made' . $x . ' {s}'; run_old()"),
        "perl -e '$label = '\"'\"'made'\"'\"' . $x . '\"'\"' {s}'\"'\"'; run_old()'",
    ),
    "a string joined to a variable after a hidden value": (
        ("perl", "-e", "$token = 'x'; print $y . ' {s}'"),
        "perl -e '$token = '\"'\"'<hidden>'\"'\"'; print $y . '\"'\"' {s}'\"'\"''",
    ),
    "a Perl quote-like word over two lines given to an ordinary name": (
        ("perl", "-e", "$label = q/made\n{s}/; run_old()"),
        "perl -e '$label = q/made\n{s}/; run_old()'",
    ),
    "a division on one line and a slash on the next in Python": (
        ("python3", "-c", "token = m/2\nlabel = a/b\nrun_old('{s}')"),
        "python3 -c 'token = <hidden>\nlabel = a/b\nrun_old('\"'\"'{s}'\"'\"')'",
    ),
}


def fill(words: tuple[str, ...], value: str) -> list[str]:
    return [word.replace("{s}", value) for word in words]


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of a word of the value that the text holds."""
    return [
        word[at : at + 6]
        for word in value.split()
        for at in range(len(word) - 5)
        if word[at : at + 6] in text
    ]


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize("row", sorted(HIDDEN_ROWS))
def test_a_credential_given_a_marked_string_is_hidden_whole(row: str, value: str) -> None:
    words, shown = HIDDEN_ROWS[row]

    out = model.public_command(fill(words, value))

    assert out == shown.replace("<hidden>", HIDDEN)
    assert pieces(out, "kiwi7mango42 plum4grape19") == []


@pytest.mark.parametrize("row", sorted(HIDDEN_ROWS))
def test_the_hash_of_a_marked_string_given_to_a_credential_holds_no_value(row: str) -> None:
    words, _ = HIDDEN_ROWS[row]
    hashed = [model.hashed_argv(fill(words, value)) for value in VALUES]

    assert hashed[0] == hashed[1] == hashed[2]
    assert pieces("\n".join(hashed[0]), "kiwi7mango42") == []


@pytest.mark.parametrize("row", sorted(SHOWN_ROWS))
def test_an_ordinary_string_and_the_words_after_a_hidden_value_show_as_typed(row: str) -> None:
    words, shown = SHOWN_ROWS[row]

    out = model.public_command(fill(words, VALUES[0]))

    assert out == shown.replace("{s}", VALUES[0]).replace("<hidden>", HIDDEN)


@pytest.mark.parametrize("row", sorted(SHOWN_ROWS))
def test_an_ordinary_string_still_tells_two_sides_apart_in_the_hash(row: str) -> None:
    words, _ = SHOWN_ROWS[row]

    assert model.hashed_argv(fill(words, VALUES[0])) != model.hashed_argv(fill(words, VALUES[1]))
