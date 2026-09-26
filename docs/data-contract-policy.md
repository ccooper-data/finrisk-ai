# Data contract policy

Every frozen modeling artifact should expose machine-readable schema evidence before model training.

Contracts record row count, columns, required fields, required-field null rates and declared unique-key violations. Schema drift is a failing condition when required fields disappear or uniqueness guarantees break.

Data contracts complement source hashes: a hash proves which bytes were used; a contract proves the structural expectations those bytes satisfied.
