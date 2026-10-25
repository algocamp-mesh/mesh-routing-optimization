# Measured simulation results

| Scenario | Method | Runs | Packets | Mean PDR20 | Min PDR20 | Target |
|---|---|---:|---:|---:|---:|---:|
| board6_warm | qgir | 2 | 33 | 1.0000 | 1.0000 | 0.98 |
| board6_warm | local_etx | 2 | 33 | 0.9722 | 0.9444 | 0.98 |
| board6_warm | dp_hoplimit | 2 | 33 | 0.9722 | 0.9444 | 0.98 |
| board6_warm | flooding | 2 | 33 | 0.5389 | 0.4667 | 0.98 |
| mesh100_warm | qgir | 2 | 23 | 0.2897 | 0.2222 | 0.98 |
| mesh100_warm | local_etx | 2 | 23 | 0.2897 | 0.2222 | 0.98 |
| mesh100_warm | dp_hoplimit | 2 | 23 | 0.9444 | 0.8889 | 0.98 |
| mesh100_warm | flooding | 2 | 23 | 1.0000 | 1.0000 | 0.98 |
| mobile20_warm | qgir | 2 | 21 | 0.3818 | 0.3636 | 0.90 |
| mobile20_warm | local_etx | 2 | 21 | 0.4318 | 0.3636 | 0.90 |
| mobile20_warm | dp_hoplimit | 2 | 21 | 0.8636 | 0.7273 | 0.90 |
| mobile20_warm | flooding | 2 | 21 | 0.8636 | 0.7273 | 0.90 |

Observed fractions are not delivery guarantees. Check seed variability, cold start, failures and the full configuration.
