# 60-second demo script

**[Terminal: repo root]**

"This is a small integration I built: a call transcript comes in by webhook, gets scored against a coaching rubric, and the result goes out to a callback URL. Standard library only, so it runs anywhere."

**[Run `python3 -m coach score samples/transcript_weak.txt`]**

"Here's a weak discovery call. The seller did 93 percent of the talking and asked no questions. It scores zero, and the coaching points at the first gap."

**[Run the mixed sample]**

"This one is more realistic. The seller found the pain and got a number, then went straight into the product. It scores 42, and the gap is the economic buyer. Nobody asked who approves the budget."

**[Start the server, send the signed curl, then the unsigned one]**

"Now the integration side. The server checks an HMAC signature on the way in. Signed request: scored. Unsigned: 401. Callbacks going out are signed the same way, so the receiver can verify them."

**[Open `coach/rubric.json`]**

"And the coaching logic lives here, in data. A sales manager can change the rubric without touching code."

**[Open the README, scroll to Honest limits]**

"I've been upfront about what this isn't: the keyword scorer is a baseline, and the model path is only tested with a mocked response. For a real customer, I'd add a queue, retries, and a calibration set before anyone gets coached on the output."
