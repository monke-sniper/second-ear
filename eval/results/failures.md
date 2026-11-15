# Wrong calls

From `eval/run_eval.py`, scorer `distilbert`. A scam call with no alert is a miss; a
legitimate call with any alert is a false alarm. The lines below are facts from the run,
and numbers in the snippets are replaced. The reason in words is for a person to add
after listening.


## Missed scams (2 of 6 scam calls)

### 02_grandparent.wav (grandparent)
- No alert. Peak score 0.9796 at 60.5 s; a caution needs a smoothed score of 0.50.
- Money ask not labelled. Call length 88.0 s.
- Heard: "that bad, but I need to pay long gift cards. Yeah, okay sure anything from my old grandson. Aw, thank you, Grandpa. I love you. Yeah, okay. So when do you want to say I love you back? Yeah, I love you, too. Please don't tell my dad. Yeah sure, there's a say between me and you. Okay. Okay. Bye."

### 14_romance.wav (romance)
- No alert. Peak score 0.0007 at 4.0 s; a caution needs a smoothed score of 0.50.
- Money ask not labelled. Call length 72.5 s.
- Heard: "appreciate it. Yeah, but I don't got no money, you know what I mean? Oh, yeah, I know you mean you pay some money. Yeah. Hey, I got you. Thank you. Thank you. Okay. like doing so much for you to sit like that long. Yeah, have a good day. Thanks, thank you. Bye. I wish you all a bye-bye."

## False alarms (1 of 6 legitimate calls)

### 05_bank_real.wav
- scam alert at 22.75 s (trigger `two_high_chunks`, score 0.9998). Peak score 0.9999.
- Heard: "Hello, I'm going to Mr Johnson. Yes. I'm calling about a mutual transaction that may have appeared on your bank account. I want to make sure you are aware of that. I'm also aware for that. The transaction we're reviewing is listed as a purchase of approximately $[number]. I don't know."

## Late alerts (after the money ask; counted as caught)
