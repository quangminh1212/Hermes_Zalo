# Security policy — Hermes_Zalo

## Unofficial client

This project uses **zca-js**, an unofficial reverse-engineered Zalo client.

- Violates Zalo Terms of Service
- Risk of temporary or permanent **account ban**
- No warranty; use at your own risk

**Always use a secondary account.** Never pair:

- Main personal identity used for banking / government
- Accounts holding money / business brand you cannot lose

## Session secrets

`credentials.json` under the session directory is equivalent to a logged-in session.

- Do not commit it
- Do not sync it to public cloud without encryption
- Restrict filesystem ACLs on shared machines

## Network

The bridge listens on **127.0.0.1** only. Do not reverse-proxy it to the public internet without auth.

## Allowlist

`ZALO_ALLOWED_USERS=*` lets anyone who can message the paired account drive the Hermes agent (shell, files). Prefer explicit UIDs in production.

## Agent power

Messages on Zalo become Hermes tool calls on the host. Treat Zalo access like SSH access to your PC.
