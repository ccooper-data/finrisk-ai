# Candidate discovery diagnostic

This workflow measures the identity-search problem without making historical-price calls.

For up to 100 distressed issuers lacking current tickers, it stores the top five discovery candidates using a deliberately broad 0.45 floor, along with top-score and top-vs-second margin distributions. No candidate is accepted or rejected by this diagnostic.

The resulting score distribution determines whether the next step should be threshold adjustment, additional identifier evidence, provider-specific alias enrichment or a different historical-security source.
