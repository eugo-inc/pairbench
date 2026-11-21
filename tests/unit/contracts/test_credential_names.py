# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Which names of variables and options look like credentials.

Two tables hold every name these tests know: names whose value is hidden and
ordinary names whose value is shown. A wide rule hides every name that holds
``TOKEN``, ``KEY``, ``SECRET``, ``PASSWORD`` or ``CREDENTIAL`` anywhere; a
name the wide rule hides may be shown only when it is listed here as ordinary.
"""

from __future__ import annotations

import itertools

import pytest

from pairbench import model

# The words of the wide rule, matched anywhere in a name.
WIDE_RULE_WORDS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL")


def wide_rule(name: str) -> bool:
    return any(word in name.upper() for word in WIDE_RULE_WORDS)


HIDDEN = (
    # Passwords and passphrases, as a whole word or at the end of a word.
    "KEYSTORE_PASS",
    "keypass",
    "--keypass",
    "storepass",
    "--storepass",
    "-storepass",
    "PASSWD",
    "MYSQL_PWD",
    "PWD",
    "OLDPWD",
    "ADMIN_PASS",
    "dbPass",
    "GPG_PASSPHRASE",
    "passphrase",
    "--passphrase",
    "GITHUB_PAT",
    "--pat",
    "AZURE_DEVOPS_EXT_PAT",
    # A pass as a whole word is hidden even where it counts passes of work.
    "-pass",
    "--two-pass",
    "pass-through",
    # Keys and the stores of keys.
    "KEY",
    "API_KEY",
    "api_key",
    "api-key",
    "--api-key",
    "apiKey",
    "APIKey",
    "APIKEY",
    "API_KEYS",
    "KEY2",
    "ACCESS_KEY",
    "access_key",
    "PRIVATE_KEY",
    "SECRET_KEY",
    "MY_KEY",
    "X_API_KEY",
    "MADEUP_SECRET_ACCESS_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "TINK_KEYSET",
    "KEYSET",
    "KEYSTORE",
    "SIGNING_KEYSTORE",
    "passKey",
    "SORTKEY",
    # A file or an identity of a key or a token, glued to the word or written apart.
    "KEYFILE",
    "keyfile",
    "--keyfile",
    "Keyfile",
    "KEYFILES",
    "KEY_FILE",
    "--key-file",
    "PRIVATEKEYFILE",
    "privatekeyfile",
    "SSH_KEYFILE",
    "ssh_keyfile",
    "sshKeyFile",
    "TOKENFILE",
    "--tokenfile",
    "HF_TOKENFILE",
    "githubtokenfile",
    "HF_TOKEN_FILE",
    "--api-token-file",
    "--auth-token-file",
    "--token-file-path",
    "--token-files",
    "KEYID",
    "keyid",
    "--keyid",
    "KEYIDS",
    "KEY_ID",
    "--key-id",
    "keyId",
    "AWS_ACCESS_KEY_ID",
    "accessKeyId",
    "TOKENID",
    "--tokenid",
    "TOKENIDS",
    "TOKEN_ID",
    "--token-id",
    # Ids of tokens with no word before them, or after a word that names a secret.
    "token_ids",
    "--token-ids",
    "api_token_ids",
    "ACCESS_TOKEN_IDS",
    "PRIVATE_TOKEN_IDS",
    # A path, a pair or a ring of keys or tokens, glued to the word or written apart.
    "KEYPATH",
    "keypath",
    "--keypath",
    "KEYPATHS",
    "KEY_PATH",
    "--key-path",
    "SSH_KEYPATH",
    "sshKeypath",
    "TOKENPATH",
    "--tokenpath",
    "HF_TOKENPATH",
    "TOKEN_PATH",
    "--token-path",
    "KEYPAIR",
    "keypair",
    "--keypair",
    "KEYPAIRS",
    "KEY_PAIR",
    "--key-pair",
    "AWS_KEYPAIR",
    "--ssh-keypair-name",
    "KEYRING",
    "keyring",
    "--keyring",
    "KEYRINGS",
    "KEY_RING",
    "--key-ring",
    "GPG_KEYRING",
    "gpgKeyring",
    "TOKENPAIR",
    "TOKENRING",
    # A key or a token glued to any word after it, as the words written apart are hidden.
    "KEYPEM",
    "--keypem",
    "KEYDATA",
    "SSHKEYDATA",
    "KEYVALUE",
    "APIKEYVALUE",
    "KEYPHRASE",
    "--keyphrase",
    "TOKENVALUE",
    "HFTOKENVALUE",
    "--tokenvalue",
    "KEYSTOREFILE",
    "--keystorefile",
    # A credential word after a word of its own that starts with KEY.
    "KEYCLOAK_PASSWORD",
    "KEYCLOAK_CLIENT_SECRET",
    "--keycloak-admin-password",
    "KEYDB_PASSWORD",
    "--keydb-password",
    "KEYEDTOKEN",
    "KEYLESS_API_KEY",
    # A secret glued after an ordinary word that ends in KEY: its S starts the secret.
    "HOTKEYSECRET",
    "MONKEYSECRET",
    "HOTKEYSECRETS",
    "--hotkeysecret",
    "TURKEYSECRET_FILE",
    "KEYSPATH",
    "KEYRINGPATH",
    "KEYRINGFILE",
    "--keyringfile",
    "KEYPAIRNAME",
    "KEYPAIRID",
    "KEYBLOB",
    "APIKEYCODE",
    "APIKEYWORD",
    "--apikeyword",
    "SSLKEYLOGFILE",
    "TOKENSTORE",
    # A password word glued to a word that names where the password is or what holds it.
    "PASSFILE",
    "--passfile",
    "PGPASSFILE",
    "PASSPATH",
    "PASSWDFILE",
    "PWDFILE",
    "PWFILE",
    "PASSPHRASEFILE",
    "PASSCODEFILE",
    "PATFILE",
    "ADMINPASSVALUE",
    "DBPASSDATA",
    "PASSFILEPATH",
    # Tokens, and TOKENS after any word that is no count.
    "token",
    "--token",
    "api_token",
    "API_TOKEN",
    "access_token",
    "HF_TOKEN",
    "MY_TOKEN",
    "A_TOKEN",
    "Z_TOKEN",
    "auth-token",
    "AUTHTOKEN",
    "HfToken",
    "AWS_SESSION_TOKEN",
    "API_TOKENS",
    "APITOKENS",
    "accesstokens",
    "HF_TOKENS",
    "GITHUB_TOKENS",
    "slackTokens",
    "hftokens",
    "--synthetic-tokens",
    # Secrets, passwords and credentials anywhere.
    "MY_SECRET_VALUE",
    "client.secret",
    "SECRETS",
    "DbPassword",
    "DB_PASSWORD",
    "PASSWORD",
    "-PASSWORD",
    "MYPASSWORD",
    "PGPASSWORD",
    "AWS_CREDENTIAL_FILE",
    "APP_CREDENTIALS",
    "SECRETARY_PASSWORD",
    "hotkey_secret",
    "monkey_token",
    # Bearer, auth and cookies.
    "bearer",
    "--bearer",
    # Short words for credentials and a web token.
    "CREDS",
    "DB_CREDS",
    "--creds",
    "gitCreds",
    "CRED",
    "--cred-file",
    "JWT",
    "--jwt",
    "API_JWT",
    "JWTS",
    "--auth",
    "BASIC_AUTH",
    "REDIS_AUTH",
    "_auth",
    "--proxy-auth",
    "OAUTH",
    "HTTP_AUTHORIZATION",
    "--authorization",
    "--cookie",
    "SESSION_COOKIE",
    # An auth word before other words, and the words for authenticating.
    "--auth-header",
    "AUTH_HEADER",
    "AUTHORIZATION_HEADER",
    "DOCKER_AUTH_CONFIG",
    "--auth-string",
    "--auth-code",
    "--authenticate",
    "AUTHENTICATE",
    "Authentication",
    "--authentication",
    # Short words for a password, a pass code and pass phrase arguments.
    "--pw",
    "-pw",
    "PW",
    "DB_PW",
    "ROOTPW",
    "--rootpw",
    "PASSCODE",
    "--passcode",
    "-passin",
    "-passout",
    # The signature of a signed address.
    "X-Amz-Signature",
    "SharedAccessSignature",
    "sig",
    "--signature",
    "--sas",
    # Connection strings.
    "AZURE_STORAGE_CONNECTION_STRING",
    "connectionString",
    "ConnectionStrings",
    "DB_CONN_STR",
    "connectionstring",
    # A measure word after a credential word still names a credential.
    "--api-key-prefix",
    "API_KEY_PREFIX",
    "--access-token-limit",
    "MAX_API_KEYS",
    "db_pass_config",
    # A credential word glued to other letters before a key or a token, before a measure or a
    # list of ids, in the same word or in a word of its own, still names a credential, as it
    # does written apart.
    "APIKEYPREFIX",
    "PRIVATEKEYSIZE",
    "MYAPIKEYPREFIX",
    "mysessiontokenprefix",
    "MYAPITOKENIDS",
    "--myaccesstokenids",
    "MYAPI_KEY_PREFIX",
    "--myapi-key-size",
    "MYPRIVATE_KEY_SIZE",
    "HFACCESS_TOKEN_BUDGET",
    "--myapi-token-ids",
    "myapi_tokenids",
)

ORDINARY = (
    # Keys that order or place data.
    "sort-key",
    "--sort-key",
    "SORT_KEY",
    "sortKey",
    "partition_key",
    "SHARD_KEY",
    "JOIN_KEY",
    "FOREIGN_KEY",
    "ROW_KEY",
    "HOT_KEY",
    "--hot-key",
    "hot-key",
    "hot.key",
    "hotKey",
    "sort.key",
    "keyword",
    "KEYBOARD",
    "KEYSPACE",
    "SORT_KEYS",
    "--sort-keys",
    "sort_key_id",
    "PARTITION_KEY_ID",
    # Words of their own that start with a key or a token, alone or glued to more.
    "KEYBOARDLAYOUT",
    "--keyboard-layout",
    "KEYWORDS",
    "keywordfile",
    "KEYSPACES",
    "--keyspace",
    "KEYFRAMES",
    "--keyint",
    "-keyint_min",
    "KEYSTROKE",
    "KEYMAPFILE",
    "KEYCODE",
    "KEYPOINTS",
    "KEYSTONE_URL",
    "KEYCLOAK_URL",
    "--keycloak-url",
    "KEYCLOAKREALM",
    "KEYDB_PORT",
    "--keydb-port",
    "KEYED_HASH",
    "--keyed",
    "KEYLESS_SIGNING",
    "--keyless",
    "tokenizermode",
    "TOKENIZERFILE",
    "--detokenize",
    "TOKENIZATION",
    "HFTOKENIZER",
    "AUTOTOKENIZER",
    # Ordinary words that end like a credential word.
    "HOTKEY",
    "hotkey",
    "MONKEY",
    "TURKEY",
    "SECRETARY",
    "MONKEYPATH",
    "HOTKEYRING",
    "TURKEYPAIR",
    "monkey-patch",
    "--monkey-patch",
    "COMPAT",
    "PYTHON_COMPAT",
    "EXPAT_DIR",
    "--with-expat",
    "BYPASS",
    "--bypass-cache",
    "COMPASS",
    "BYPASSFILE",
    "COMPASSPATH",
    "COMPATFILE",
    "PASSPORTFILE",
    "--passive",
    # Counts and sizes of tokens.
    "tokens",
    "TOKENS",
    "Tokens",
    "--tokens",
    "max-tokens",
    "--max-tokens",
    "MAX_TOKENS",
    "maxTokens",
    "max.tokens",
    "maxtokens",
    "MAXTOKENS",
    "maxnewtokens",
    "num_tokens",
    "output-tokens",
    "--output-tokens",
    "OUTPUT_TOKENS",
    "outputTokens",
    "output_tokens",
    "output.tokens",
    "outputtokens",
    "OUTPUTTOKENS",
    "prompt_tokens",
    "MAX_NEW_TOKENS",
    "max_completion_tokens",
    # A file of tokens, named with nothing more.
    "TOKEN_FILE",
    "--token-file",
    "token.file",
    "tokenFile",
    # The most tokens, named with one token.
    "MAX_TOKEN",
    "MAXTOKEN",
    "max-token",
    "--max-token",
    "max.token",
    "maxToken",
    "maxtoken",
    "budget_tokens",
    "skip_special_tokens",
    "--max-num-batched-tokens",
    "--num-speculative-tokens",
    "--max-input-tokens",
    "--max-total-tokens",
    "--max-batch-prefill-tokens",
    "--max-waiting-tokens",
    "--max-prefill-tokens",
    "--synthetic-input-tokens-mean",
    "--output-tokens-mean",
    "--tokens-per-second",
    "tokenizer",
    "TOKENIZERS_PARALLELISM",
    "--tokenizer-mode",
    "--tokenizer-file",
    "--tokenizer-path",
    "TOKENIZER_PATH",
    "tokenizerpath",
    # One token of a model's vocabulary.
    "EOS_TOKEN",
    "--eos-token",
    "eos-token",
    "eos.token",
    "eosToken",
    "EOS_TOKENS",
    "EOSTOKENS",
    "EOSTOKENSFILE",
    "--eos-tokens",
    "eos-tokens",
    "eos.tokens",
    "eosTokens",
    "eostokens",
    "eos_token_id",
    "eostokenid",
    "--stop-token-ids",
    "stoptokenids",
    # A list of the ids of tokens of a model's vocabulary, as vLLM's sampling parameters name them.
    "allowed_token_ids",
    "--allowed-token-ids",
    "ALLOWED_TOKEN_IDS",
    "logprob_token_ids",
    "prompt_logprob_token_ids",
    "trace_decode_token_ids",
    "pad_token",
    "bos_token",
    "--long-prefill-token-threshold",
    # Switches and settings around auth and cookies.
    "--no-auth",
    "--disable-auth",
    "ENABLE_AUTH",
    "--auth-type",
    "--authorization-mode",
    "--cookie-jar",
    "--no-cookies",
    "--auth-mode",
    "--auth-method",
    "--auth-scheme",
    "--authentication-type",
    "--proxy-auth-type",
    "--no-auth-header",
    "AUTHOR",
    "--author",
    # Settings around a signature.
    "--signature-version",
    "--no-signature",
    "--sig-figs",
    "SIGTERM",
    # Ordinary words that start like a short word for credentials.
    "CREDIT",
    "--credit-limit",
    "INCREDIBLE",
    # Ordinary words that hold a password word inside.
    "PASSES",
    "--passes",
    "passthrough",
    "--patience",
    "PATH",
    "--pattern",
    "SPATIAL",
    # Counts and sizes of tokens a server schedules or a client asks for.
    "--max-num-queued-tokens",
    "--max-num-scheduled-tokens",
    "--dbo-decode-token-threshold",
    "--token-budget",
    "--rankings-passages-prompt-token-mean",
    "--rankings-passages-prompt-token-stddev",
    "inter_token_latency",
    "--use-server-token-count",
    # A compiler setting whose first word is PASS.
    "pass_config",
    "--pass-config",
    # Sizes, counts and shapes of the keys a client writes.
    "--key-prefix",
    "--key-minimum",
    "--key-maximum",
    "--key-pattern",
    "--key-stddev",
    "--key-median",
    "--key-size",
    "key_size",
    "--key_size",
    "--keys_per_prefix",
    "--num-keys",
    "NumKeys",
    "--max-keys",
    # The same with the measure glued to the key or the token, after another word or not.
    "KEYSIZE",
    "--keysize",
    "keysize",
    "KEYSIZES",
    "--keystddev",
    "HFKEYSIZE",
    "--ssh-keysize",
    "HFTOKENSIZE",
    # Keys alone, and the largest key, in each spelling the wide rule writes.
    "KEYS",
    "keys",
    "Keys",
    "--keys",
    "MAX_KEY",
    "max-key",
    "--max-key",
    "max.key",
    "maxKey",
    "MAXKEY",
    "maxkey",
)


@pytest.mark.parametrize("name", HIDDEN)
def test_a_name_of_the_hidden_table_looks_like_a_credential(name: str) -> None:
    assert model.looks_like_credential(name) is True


@pytest.mark.parametrize("name", ORDINARY)
def test_a_name_of_the_ordinary_table_does_not_look_like_a_credential(name: str) -> None:
    assert model.looks_like_credential(name) is False


def test_no_name_is_in_both_tables() -> None:
    assert set(HIDDEN).isdisjoint(ORDINARY)


# Words before a credential word, and the words themselves, written in each
# spelling a variable or an option is written in.
LEADS = ("", "API", "ACCESS", "MY", "HF", "GITHUB", "PRIVATE", "TINK", "CLIENT", "MADEUP", "DB")
ORDINARY_LEADS = ("SORT", "HOT", "MAX", "OUTPUT", "EOS")
WORDS = (
    "KEY",
    "KEYS",
    "TOKEN",
    "TOKENS",
    "SECRET",
    "SECRETS",
    "PASSWORD",
    "CREDENTIAL",
    "CREDENTIALS",
    "KEYSTORE",
    "KEYSET",
    "KEYFILE",
    "KEYID",
    "TOKENFILE",
    "TOKENID",
    "KEYPATH",
    "KEYPAIR",
    "KEYRING",
    "TOKENPATH",
    "KEYPEM",
    "KEYDATA",
    "KEYVALUE",
    "TOKENVALUE",
    "KEYSPATH",
    "KEYRINGPATH",
    "KEYPAIRNAME",
)


# A name that glues words to a word of a key or a token hides its value exactly when the name
# that writes them apart does: the words before it, the words of a key or a token, and the
# words after it, one or two. The lead before a key stays glued to it as typed (``SORTKEY`` is
# hidden as one word), so it holds no word that orders or places data.
APART_LEADS = ("", "API", "HF", "MY", "SSH", "GPG", "AWS", "PRIVATE", "EOS", "STOP", "BOS")
APART_HEADS = ("KEY", "KEYS", "KEYSTORE", "KEYSET", "TOKEN")
APART_TAILS = (
    ("FILE",),
    ("FILES",),
    ("PATH",),
    ("ID",),
    ("IDS",),
    ("PAIR",),
    ("RING",),
    ("PEM",),
    ("DATA",),
    ("VALUE",),
    ("PHRASE",),
    ("NAME",),
    ("BLOB",),
    ("SIZE",),
    ("TYPE",),
    ("URL",),
    ("DIR",),
    ("RING", "PATH"),
    ("RING", "FILE"),
    ("PAIR", "NAME"),
    ("PAIR", "ID"),
    ("FILE", "PATH"),
    ("ID", "LIST"),
    ("SIZES",),
    ("STDDEV",),
    ("PREFIX",),
    ("LEN",),
    ("MAX",),
)
# The same for a word of a password, glued to a word that names where the password is or what
# holds it.
APART_PASSWORD_LEADS = ("", "PG", "DB", "MY", "ADMIN", "ROOT", "KEYSTORE")
APART_PASSWORD_WORDS = ("PASS", "PASSWD", "PWD", "PW", "PASSPHRASE", "PASSCODE", "PAT")
APART_PASSWORD_TAILS = (
    ("FILE",),
    ("FILES",),
    ("PATH",),
    ("ID",),
    ("VALUE",),
    ("DATA",),
    ("PEM",),
    ("HASH",),
    ("HASHES",),
    ("TEXT",),
    ("FILE", "PATH"),
)


def glued_and_apart(lead: str, head: str, tail: tuple[str, ...]) -> list[tuple[str, str]]:
    """The spellings of a name glued and written apart, as pairs that must agree."""
    words = [word for word in (lead, head, *tail) if word]
    glued = "".join(words)
    return [
        (glued, "_".join(words)),
        (glued.lower(), "-".join(words).lower()),
        ("--" + glued.lower(), "--" + "-".join(words).lower()),
    ]


# The one name read otherwise: a file of tokens written apart and alone is shown, while the same
# words glued stay hidden.
GLUED_TOKEN_FILE_PAIRS = [
    ("TOKENFILE", "TOKEN_FILE"),
    ("tokenfile", "token-file"),
    ("--tokenfile", "--token-file"),
]


def test_a_name_glued_to_a_key_or_a_token_hides_exactly_as_written_apart() -> None:
    pairs = [
        pair
        for lead, head, tail in itertools.product(APART_LEADS, APART_HEADS, APART_TAILS)
        for pair in glued_and_apart(lead, head, tail)
    ]
    differ = [
        (glued, apart)
        for glued, apart in pairs
        if model.looks_like_credential(glued) != model.looks_like_credential(apart)
    ]
    assert differ == GLUED_TOKEN_FILE_PAIRS


def test_a_name_glued_to_a_password_word_hides_exactly_as_written_apart() -> None:
    pairs = [
        pair
        for lead, word, tail in itertools.product(
            APART_PASSWORD_LEADS, APART_PASSWORD_WORDS, APART_PASSWORD_TAILS
        )
        for pair in glued_and_apart(lead, word, tail)
    ]
    differ = [
        (glued, apart)
        for glued, apart in pairs
        if model.looks_like_credential(glued) != model.looks_like_credential(apart)
    ]
    assert differ == []


def spellings(lead: str, word: str) -> set[str]:
    if not lead:
        return {word, word.lower(), f"--{word.lower()}", word.capitalize()}
    return {
        f"{lead}_{word}",
        f"{lead}-{word}".lower(),
        f"--{lead}-{word}".lower(),
        f"{lead}.{word}".lower(),
        lead.lower() + word.capitalize(),
        lead + word,
        (lead + word).lower(),
    }


def generated() -> list[str]:
    names: set[str] = set()
    for lead, word in itertools.product(LEADS, WORDS):
        names |= spellings(lead, word)
    for lead, word in itertools.product(ORDINARY_LEADS, ("KEY", "TOKEN", "TOKENS")):
        names |= spellings(lead, word)
    return sorted(names)


def test_every_name_the_wide_rule_hides_is_hidden_unless_listed_as_ordinary() -> None:
    names = sorted({*generated(), *HIDDEN, *ORDINARY})
    shown = [
        name
        for name in names
        if wide_rule(name) and not model.looks_like_credential(name) and name not in ORDINARY
    ]
    assert shown == []


def test_the_tools_own_flags_and_config_keys_look_like_credentials_only_where_listed() -> None:
    names = {key.rpartition(".")[2] for key in model.CONFIG_KEYS}
    found = sorted(name for name in names if model.looks_like_credential(name))
    # The list of variables forwarded without a value: its own value is a
    # list of names, which the recorded config keeps.
    assert found == ["env_pass"]
    assert model.redact_argv(("pairbench", "run", "--set", "launch.env_pass=HF_TOKEN")) == (
        "pairbench",
        "run",
        "--set",
        "launch.env_pass=HF_TOKEN",
    )
