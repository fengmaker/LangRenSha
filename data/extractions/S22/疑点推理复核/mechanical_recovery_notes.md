# Mechanical review recovery notes

This is a temporary recovery note only; it is not the requested plan and does not replace evidence-based review. The review queue has 46 games and 88 questions. Current `exec_command` and `node_repl` both fail before execution (`setup refresh had errors`); elevated shell execution was rejected by automatic approval due to a usage limit. Do not invent question IDs, source quotes, timestamps, or dossier hashes to compensate.

## Confirmed conclusions retained from the prior review

- BV1dJ7R6fEUw: R1 seer checks #2; result is Guard. R2 wolves target #2 (cross-line command “击杀。二号守卫”); R2 night deaths include #2 and #9. R3 wolves target #4 and seer checks #1 as wolf. The raw R3 phrase is “入夜狼人击杀。四号通灵师通灵师，验证一号安家威狼人身份”; segment order and later death announcement support kill #4, check #1.
- BV1zX7C6qEmR: additional seer result suspect R3 target #4 is Peasant. R2 mech witch passes; standard seer checks #9 as Wolf. R3 mech-witch poison #7 is plausible from the explicit poison/death wording but should be source-checked before finalizing.
- BV1W6jG6HEkC: additional seer result suspects: R1 target #10 is Witch; R3 target #7 is Hunter. Mech wolf seat #8 learns from #3.
- BV1xkL96MEsd: R1 witch poison kills #5. Additional result suspects: R2 target #1 is Hunter; R3 target #7 is Peasant.
- BV1Wjja66EFz: R1 night death #1 despite same-target save and guard protection; R2 death #6 via witch poison while wolf target #10 is guarded. Additional result suspects: R1 target #3 Peasant; R3 target #8 Peasant; R4 target #10 Witch.
- BV1nBj664EFS: R1 death #7 from mechanical-witch poison, then mech is dead and cannot act in R2/R3. R2 guard passes; seer #9 checks #1 as Wolf. R3 wolf target #10; Hunter #10 checks #12 as Peasant. Additional result suspects include R1 target #11 Peasant, R3 target #12 Peasant.
- BV13Ajo6xEY8: additional result suspects R1 target #7 Peasant, R2 target #5 Witch, R3 target #3 Hunter.
- BV1suMG6PEYP: seat #9 is Peasant by role-count elimination; R3 kill #2 Guard is a likely but still source-checkable inference.
- BV13ZMp63EEB: R3 guard pass is supported; R3 death #9 cannot be assigned to wolf attack without excluding the surviving witch's poison, so leave that cause pending.
- BV1VxNH6YETC: seat #9 Guard by board-count/context; R1 guard passes; R2 seer target #9 result Guard.
- BV1YxNH6YEqY: R2 guard self-protects #6 (“自首” likely ASR for 自守).
- BV1BPNB6QE4z: R4 ordinary wolf target #11 is guarded; witch poison kills #4.
- BV12pNo6HEiz: R2 target #11 is wolf; seer result should be Wolf.
- BV1bWKY6tEri: R2 night deaths #10 and #11; retain four rounds because R4 is explicit.
- BV1DFM26ME2o: R3 guard protects #4; wolves target #2. Do not substitute candidate guard #6 / wolf #3.
- BV1mDun6wE3m: R1 guard passes explicitly.
- BV12Mur6nEns: R2 check of #12 as “通灵师” is valid if #12 is mech wolf who learned seer; endgame “选择招牌” likely ASR for 交牌 but is not modeled as an event.
- BV1WigN6JEVS: R2 mech-seer #1 checks #3 as Guard. By R3 all ordinary wolves have died; #1 is the carrier using ordinary wolf attack on #8, not mechanical skill attack. Keep final “交牌” unmodeled/pending.
- BV1kG8A6dE7A: R2 regular seer feedback on mech wolf #4 who learned seer is “通灵师”; mech seer #4 checks #11 as Guard.
- BV18W8B6KE7C: R2 poison kills mech wolf #7. Since mech is dead, R3 mech action must be unavailable/dead; R3 regular guard passes.

Other reviewed issues retained from prior analysis include game 6 round-4 ordinary knife target #10 and doubleblade target #7; game 7 same-guard/same-save causes target #12 to die; game 13/14/16 mechanical actions become unavailable after those mechs are dead/exiled; game 30 R1 check #10 should report Guard; game 31 guard self-protects #2; game 32 R3 seer target #9 result Guard; game 35 R3 guard target #4 and wolf target #2; game 42 R3 uses ordinary wolf knife from mech carrier on #8 after all ordinary wolves are gone; game 46 R2 poison kills mech wolf #7.

The final `mechanical_plan.json` still needs to be generated from the queue so each of the exact 88 input question IDs has one decision with a verbatim source quote, source path, timestamp, and dossier SHA-256. Apply only verified change suggestions; retain unresolved items where the summaries identify competing causes or unsupported event slots. Run `validate(copy, allow_incomplete=True)` only after composing the final merged copy, and report validator constraints without dropping true facts.
