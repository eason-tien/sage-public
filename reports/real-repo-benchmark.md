# Real-Repository Gate Portability Benchmark

Generated: 2026-07-13T03:27:52.593941+00:00

External repository contents were treated as untrusted data. No build, test, hook, or repository script was executed.

| Language | Repository | Commit | Files | Gate candidate | Benchmark | Strict gates |
|---|---|---:|---:|---|---|---|
| python | [pallets/itsdangerous](https://github.com/pallets/itsdangerous/commit/672971d66a2ef9f85151e53283113f33d642dabd) | `672971d66a2e` | 50 | pytest | PASS | PASS |
| javascript | [sindresorhus/slugify](https://github.com/sindresorhus/slugify/commit/7c318bd1aa4b4affab29761f15a9604323fe2a3b) | `7c318bd1aa4b` | 13 | node-test | PASS | PASS |
| go | [fatih/color](https://github.com/fatih/color/commit/53d4ce9d5df3891799a447e772308c76e70bad50) | `53d4ce9d5df3` | 10 | go-test | PASS | PASS |
| rust | [BurntSushi/memchr](https://github.com/BurntSushi/memchr/commit/bce7df7140acff420478a358cde5587904000cb1) | `bce7df7140ac` | 183 | cargo-test | PASS | PASS |
| java | [junit-team/junit4](https://github.com/junit-team/junit4/commit/300468b1efd48d76fac2f7bd6d576846dcbbf5ed) | `300468b1efd4` | 619 | project-wrapper | PASS | PASS |
| kotlin | [square/moshi](https://github.com/square/moshi/commit/889013ec2edb8d8034902662a1dc8c4f3b3f8111) | `889013ec2edb` | 183 | project-wrapper | PASS | PASS |
| ruby | [rack/rack](https://github.com/rack/rack/commit/0a07b6e74c102a138773b7add73bbd4aba185ef4) | `0a07b6e74c10` | 185 | bundle-test | PASS | PASS |
| php | [sebastianbergmann/version](https://github.com/sebastianbergmann/version/commit/bce09f605bea2f286401dc0a55db655609ba0c4c) | `bce09f605bea` | 171 | composer-test | PASS | FINDINGS |
| csharp | [spectreconsole/spectre.console](https://github.com/spectreconsole/spectre.console/commit/3ba1023095399bb6a50d4f9f2f194d3d4d28187e) | `3ba102309539` | 784 | dotnet-test | PASS | PASS |
| swift | [apple/swift-argument-parser](https://github.com/apple/swift-argument-parser/commit/e579882f95579e7d7eb8c8068a5925c65d361e91) | `e579882f9557` | 270 | swift-test | PASS | PASS |
| c | [DaveGamble/cJSON](https://github.com/DaveGamble/cJSON/commit/fb16e5cf358798aabb049655975cde8427101056) | `fb16e5cf3587` | 229 | project-build | PASS | FINDINGS |
| lua | [rxi/json.lua](https://github.com/rxi/json.lua/commit/dbf4b2dd2eb7c23be2773c89eb059dadd6436f94) | `dbf4b2dd2eb7` | 10 | lua-test | PASS | PASS |

Overall: **PASS** — 12/12 pinned repositories were valid; 10 passed every strict gate.

## Strict-gate findings

These are compatibility findings, not suppressed failures:

- **sebastianbergmann/version**: 5 redacted Gitleaks findings at `tools/.phpstan/vendor/phpstan/phpstan/phpstan.phar:569909`, `tools/.phpstan/vendor/phpstan/phpstan/phpstan.phar:569924`, `tools/.phpstan/vendor/phpstan/phpstan/phpstan.phar:86680`.
- **DaveGamble/cJSON**: 4 redacted Gitleaks findings at `tests/unity/test/testdata/testRunnerGenerator.c:115`, `tests/unity/test/testdata/testRunnerGenerator.c:127`, `tests/unity/test/testdata/testRunnerGeneratorWithMocks.c:116`, `tests/unity/test/testdata/testRunnerGeneratorWithMocks.c:128`.
