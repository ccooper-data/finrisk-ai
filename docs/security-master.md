# Historical security master contract

The security master separates issuer identity from security identity.

Every security record requires a stable security ID, issuer ID, security name, valid-from/to interval and source provenance. Symbol/ticker is optional metadata, not the primary key.

Validity intervals are mandatory because a ticker or security relationship can change over time. Conflicting/overlapping evidence is reported for adjudication rather than silently collapsed.
