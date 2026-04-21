# 📥 NEW INBOX (Unprocessed)
1. I now added the claude code extension, so I can use that for coding and planning as well. I also mentioned ChatGPT previously, I wonder if that could be tied in. But really I want to figure out the best workflow that plays on Claud vs. Antigravity's Strength's. 
2. Tracking my input and ideas that I directly chat with the AI's about and adding that to a file in docs
3. I think this largely is tied in with engine A, but finding stocks that actually could be hypothetically profitable like defense stocks or oil with a war 
4. An information pipeline - could be for the machine to make better trades like info about markets, either from papers or online sources, or could be for the machine itself to improve
---
# 🗄️ PROCESSED ARCHIVE

**[2026-03] Roadmap & Architecture Refinement Concepts**
- 1. When an idea is added to the roadmap once out of this pipeline, it should have an overarching goal, but then that goal should be broken down into smaller actionable steps. 
- 2. For the above, this needs to be included in our documentation as well. 
- 3. The documentation itself should have an overview file 
- 4. We need to clean up the codebase, and consolodate the folders and files so an AI can better view everything
- 5. In docs/Core/PROJECT_CONTEXT.md we need to create a diagram for how the machine should work, and below this what folders are relevant for that. 
- 6. I am not sure the index.md files are 100% accurate in engines/ (excluding data_manager)
- 7. This relates to 6, we need to make sure the documentation around each of the engines is 100% accurate. At this point, I'm not even sure what specifically each engine should and shouldn't do. This all started from a simple idea, but it's gotten very complex and now we are in the thick of things without 100% exact clarity on what we're doing. This is something to do a little later, after some of the above but before we start making major changes or including more info about these, so we know the changes to make.

Need to figure out how to incorporate better
- machine learning
- news/geopolitical scraping and analysis

regime detection should be it's own engine, this actually might be the most important part of the system
https://www.reddit.com/r/algotrading/comments/11fyy87/what_market_regime_detection_methods_have_you/
https://medium.com/@amina.kaltayeva/market-regime-detection-why-understanding-ml-algorithms-matters-4eb7e8cac755


a system should "understand when a signal should matter and when it should be ignored"

I wonder if theres any way to incorporate chatgpt into this - i can invite via email for my trading machine folder - LOOK at the chat Automated Trading Insights 

both longer term swing trading (which is sort of what we have right now) and short term/intraday trading (especially as a hedging mechanism - i.e. during a downturn we can still make money intraday (especially if there is volatility) to recoupe some of our losses on our long term positions )


I feel like the agent should have a better way to injest information - if I have a file like this, it looks through it and assigns different agents to different aspects of the tasks. I do think we will need to improve the pipeline, but if we do we could see big returns. 

- Call spread, need to understand options chains

leveraged etfs for day only 

ways to hedge the market - this was why we tried including some of the info from the summaries in Other/credits
including market news into the system. The goal here was to be able to have the system work like a real trading desk operator, not just a machine.  

drawdown 
not ridgid stop losses but a better version


Things in the future - I don't know much about options so I can't direct as well on this one but especially for hedging and compounding returns with low capital - this will be very helpful, but also add a significant layer of complexity and risk

Agents/workflows/skills
- this is really where we need to improve
- look at dexter on github! not only interesting software, but shows some good best practices. Also with dexter, this would be VERY interesting to incorporate into our system - would help with narrative + foundational edge 
- I also think that we should try learning more about the best practices to do what we are trying to do 

Review https://www.anthropic.com/engineering/building-effective-agents - interesting distinction between Workflow and Agents, I feel like maybe part of our problem is we were calling workflows agents? - maybe even have agent review the link


What other papers would be good to include? I'm thinking we 1. find some good papers for A. finding alpha B. machine learning (maybe look at book titles in goodreads for inspiration - a lot of these were added thinking about this) C. portfolio management D. risk management E. anything else I've missed - diversity/hedging/rotation/learning/compound/bond yields/idk theres SO much. The goal would be to find some really good but dense papers and do like what we did with parrondo

https://addyosmani.com/blog/ai-coding-workflow/
https://blog.tedivm.com/guides/2026/03/beyond-the-vibes-coding-assistants-and-agents/



this might add some value - https://barebone.ai/

a much greater overall emphasis on predicting regimes and using that information to then test strategies on. need to focus on other things - vix is one but how about the bond market, treasury yields, etc. 

a new file where I enter in new ideas, and the agent takes those ideas and adds them to the list of future additions in whatever file has that future roadmap 

using prediction markets for other sets of information

13F filing

- repo markets - SOFR rates, fed repo facility usage, overnight reverse repo

international markets 

OpenBB - like bloomberg but free

yield curve

FinGPT to review

kalman filter vs moving average

QuantLib, PyPortfolioOpt, Qlib, 

pandas, backtrader, TA-Lib, cctx, NumPy

calmer ratio

- finding stocks based on geopolitical events 
- policy impact on stocks 
- stripper index + adult sites prediction model 
- bond market/debt
- sector rotation 
- “i don’t know much about stocks (to chat gpt?) but here’s what I’ve built, what’s it missing? what issues do you see with it? where can it be improved? 
    - using better prompts like the 7 on insta to have better features
- outside of the roadmap - a forward looking doc for aspects we plan for in the future 
    - sortve had this in past but the it gets biased towards this and hung up where it starts going down a narrow hole
- markov chains for regimes? what other math 

## Areas needing improvement
This is slightly different from the above, they are not completly new things, but areas or ways I think the system should be improved
- Portfolio management - right now "we have a very basic portfolio management system, but it could be much better. We should be able to allocate capital to different strategies based on their performance, and we should be able to rebalance the portfolio based on market conditions." (AI generated but yes) Actually what I was getting at is we have no diversification, no hedging, no rotation, no real way to test what preforms better or worse (like how the rest of the system does) and no uncorrellated strategies
- On the topic of portfolio (this actually is more for the above) but having portfolio sleeves "Portfolio sleeve investing divides a single, unified investment account into separate, virtual sub-accounts (sleeves) managed independently for specific strategies, asset classes, or managers. This approach allows for highly customized, tax-efficient management, such as isolating legacy stocks or blending different investment styles."
- kelly criterion
- continuous learning - this is the overall emphasis - yes of edges, but also of entry/exit points, best diversification, best risk management, best portfolio management, best times to use certain strategies, best times to hedge, best times to go long or short, best times to do nothing, etc. (autosuggest but some good)
- **Finding good stock picks** - it doesn't really seem to do this. It can decide it seems like when to buy and sell, but it doesn't really seem to find those good stocks that have the fundamental + technical indicators showing it will explode
- a lot of technical indicators or "edges" that are known don't always work, the machine obviously can start with those, but it should be able to find new ones and adapt to the market. 

The goal is FINDING the strategies that work, then backtesting them, then paper trading them on the live markets, and if they pass all of that, are they only then deployed for real money 

When we are testing the system we should have two live traders - one that is testing new strategies and one that is trading with the strategies that we already know work. First it will be 2 sets of paper traders, then when we are confident in our system, it will be one paper trader, and one with real money