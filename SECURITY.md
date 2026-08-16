# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately through GitHub Private Vulnerability Reporting when it is enabled for this repository. Do not open a public issue containing private keys, Nostr secrets, encrypted credential material, bunker connection secrets, authentication cookies, or other sensitive operational data.

## Sensitive material

This repository must never contain:

- Nostr identity private keys (`nsec`, hex secrets, or decrypted equivalents)
- NIP-46 client private keys
- `*.cred` systemd encrypted credential files
- YouTube/browser cookies
- live bunker one-time connection secrets
- local state copied from `~/.config/nak` or `~/.local/state`

Public keys, Nostr event IDs, relay URLs, and public stream URLs are not secrets.

## Operational security

The recommended deployment keeps the Nostr identity key in a systemd encrypted credential and exposes signing through a dedicated `nak bunker` process. Automation uses a separate authorized NIP-46 client key rather than the identity private key directly.

The bunker is intentionally launched with `nak -q`. Review `nak` release behavior before removing quiet mode: some versions can print a restart command that includes a supplied signer secret.

If a signer key is ever emitted to a terminal transcript, journal, issue, chat, or other untrusted location, treat that key as compromised and rotate it where practical.
