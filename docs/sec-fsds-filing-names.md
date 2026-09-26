# SEC filing-era registrant names

The SEC Financial Statement Data Sets provide SUB records keyed by accession and CIK. SEC documentation defines SUB.name as the registrant legal-entity name recorded in EDGAR as of the filing date.

FinRisk uses this as the primary bulk historical-name backbone from 2009 forward. Each quarterly ZIP is hashed before filtering to the hard-case CIK cohort.

Filing-era registrant names remain issuer identity evidence. They do not establish ticker/security continuity through bankruptcy, merger or reorganization.
