from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXPECTED_INPUT_SHA256 = "50fb33e1b658a28af56bc73c8e7a095bcddbc7bb80235cba67aee0cf40acfb8f"

EXACT_OVERRIDES = {
    # Database names, descriptions, locations, and system terms.
    "Ya boi!": "你兄弟我！",
    "Come here boy!": "过来，小家伙！",
    "Ocarina fluit to play songs": "能演奏歌曲的陶笛。",
    "wood": "木板",
    "General Armor": "通用护甲",
    "Command Remember": "指令记忆",
    "Optimize": "最强装备",
    "Clear": "全部卸下",
    "M.Attack": "魔法攻击",
    "M.Defense": "魔法防御",
    "Elysium": "至福乐土",
    "Fields of Asphodel": "阿斯福德尔原野",
    "Asphodel Plaza": "阿斯福德尔广场",
    "Minotaur Den": "弥诺陶洛斯巢穴",
    "Inside Tavern": "酒馆内部",
    # Elysium dialogue reviewed as contiguous RPG Maker message blocks.
    "The water is so refreshing here! I just melt :D": "这里的水太舒服了！人家都要化了 :D",
    "Do I... know you?": "我……认识你吗？",
    "While I think about it, can you do a task for me?": "趁我回忆的时候，能帮我个忙吗？",
    "I remember Perseus dropping Medusa's ": "我记得珀尔修斯把美杜莎的",
    "sunglasses a sewer grate, mind finding ": "墨镜掉进了下水道，能麻烦你",
    "them and giving them to her?": "找回来还给她吗？",
    "Yes dear, she's in the building to the \\C[20]right\\C[0].": "是的，亲爱的。她就在\\C[20]右边\\C[0]那栋楼里。",
    "Take care to avoid eye-contact, she doesn't ": "千万别跟她对视，她可不",
    "like that.": "喜欢别人这么做。",
    "Fine, good luck reaching your husband then.": "好吧，那就祝你能顺利找到丈夫。",
    "Orus? The man you've been following this": "奥鲁斯？就是你一路跟着的那个男人？",
    "entire time? He's been trying to lead": "他老早就在想办法带你",
    "you out for ages.": "离开这里了。",
    "more task for you though.": "不过还得再请你帮一个忙。",
    "and win back my\\..\\..\\..": "帮我赢回我的\\..\\..\\..",
    "He can easily be spotted with the constant": "他身边总是围着一群人，很好认。",
    "crowd around him, you'll have to get rid of": "你得先想办法把那些人",
    "them somehow.": "赶走。",
    "Slippers removed.": "已交出拖鞋。",
    "Here is your new and improved instrument!": "这是给你的新乐器，已经改良过了！",
    "but some prince took it as a form of \"royal ": "不过某位王子以“王室税收”的名义",
    "taxes\", you should try and get it from him.": "把乐谱拿走了，你得想办法找他要回来。",
    "It has been over \\{TWELVE HOURS\\}.": "都已经\\{十二个小时\\}了。",
    "When will Oddyseus ever stop playing.": "奥德修斯到底还要玩到什么时候？",
    "Wow you scared those spirits deeper into ": "哇，你把那些游魂吓得逃向了",
    "the underworld!": "冥界深处！",
    "and then given the chance to \"Hit\" or \"Hold\".": "接着你可以选择“要牌”或“停牌”。",
    "You can take the chance and add to the cards": "选择“要牌”可以再拿一张牌，",
    "you already have with \"Hit\". But if you ": "但如果总点数超过21点，",
    "go over 21, you \"bust\". Basically you lose.": "你就会“爆牌”，也就是输掉这局。",
    "And if I'm closer to 21 than you are,": "如果我的点数比你更接近21点，",
    "Here are some slippers I won off some": "这双拖鞋是我从一个",
    "weird musician.": "古怪的乐师手里赢来的。",
    "You've recieved \\C[20]Slippers\\C[0]!": "获得了\\C[20]拖鞋\\C[0]！",
    "Unless you wish to share the fate of my ": "除非你也想落得我那些",
    "...unfortunate customers.": "……倒霉客人的下场。",
    "My sunglasses? Yeah, I lost them a while": "我的墨镜？对，我前阵子弄丢了。",
    "ago. Not sure where they are though...": "不过我也不清楚掉在哪儿了……",
    "Maybe someone else has seen them.": "也许有人见过。",
    "it's on the house. \\}*wink*": "这次算我请客。\\}*眨眼*",
    "I've been bested. Did you see that Ri? ": "我居然输了。看见了吗，里？",
    "Hippolyta is a queen among woman!": "希波吕忒可是女中豪杰！",
    "While I won this time, it was a close match!": "这次虽然是我赢了，但胜负只在毫厘之间！",
    "Use davul to smash?": "用达武尔鼓砸开吗？",
    "I need something to break this with.": "我得找件东西把这里砸开。",
    "\\}Imighthavedroppedsomethingdownthedrain\\fr": "\\}我好像把什么东西掉进下水道了\\fr",
    "I can't reach down there myself without ": "不砸开栅栏，我自己够不着下面，",
    "breaking down the gate, but I don't ": "可我手头又没有",
    "have anything that could.": "能砸开它的东西。",
    "Ugh, you look like the gum at the ": "啧，你就像粘在我粉色鞋底的",
    "bottom of my pink shoes. Pitiful.": "口香糖。真可怜。",
    "\\}Deep breaths Ri, deep breaths, calm...\\{": "\\}深呼吸，里。深呼吸，冷静……\\{",
    "Good riddance!": "赶紧滚吧！",
    "Oh Aegeus, I love you more than": "噢，埃勾斯，我爱你胜过",
    "I love father's treasury.": "父亲的宝库。",
    "Mmmmm yes, out with it filthy peasant.": "嗯……有事快说吧，肮脏的平民。",
    "can't have it.": "你可拿不到。",
    "I need it to persuade this fine lady": "我还得靠它说服这位漂亮姑娘",
    "to go out with me.": "跟我约会呢。",
    "Oh my sunshine, I love you more than": "噢，我的小太阳，我爱你胜过",
    "taxing the poor.": "向穷人征税。",
    "You have recieved \\C[14]Song of Persuasion\\C[0]!": "获得了\\C[14]劝服之歌\\C[0]！",
    "You are Orus are definitely a better match.": "你和奥鲁斯才是天生一对。",
    "Those two have been standing there for \\{Ag\\}es!": "那两个人已经站在那里\\{好\\}久了！",
    # River Styx, labyrinth, and Cerberus dialogue.
    "\\..\\..\\..Three tasks, three fates, three obstacles\\..\\..\\..": "\\..\\..\\..三项任务，三种命运，三道障碍\\..\\..\\..",
    "you’ve yet to succeed in your final challenge. ": "可你还没能通过最终考验。 ",
    "Oh. Unfortunately, we meet again, Ri.": "哦。真遗憾，我们又见面了，里。",
    "Excuse me--!": "不好意思——！",
    "--You.": "——你。",
    "I'd give you a ride, but I only ": "我倒是愿意载你一程，可我只负责",
    "ferry souls into the underworld,": "把灵魂送进冥界，",
    "not out of it": "不负责送出去。",
    "...Right.": "……好吧。",
    "Would you like to cross?": "要过河吗？",
    "Let me teach you \\c[14]Song of Soothing\\c[0],": "让我教你\\c[14]安抚之歌\\c[0]，",
    "Last time: ": "最后再来一遍：",
    "If you ever forgot what it was, return to me.": "要是忘了，就回来找我。",
    "Oh, and before I forget to tell you": "哦，差点忘了告诉你：",
    "Song 1 is: ": "第一首曲子是：",
    "*muffled* AAAAHHH, not again.": "*含糊地* 啊啊啊啊，怎么又来了。",
    "The only time he will sit, is when its": "它只肯在一个地方坐下，",
    "on me...": "就是我身上……",
    "\\{GRr\\}rr!": "\\{呜\\}汪！",
    "You have recieved ball!": "获得了球！",
    "Do you want to pet Cerberus?": "要摸摸刻耳柏洛斯吗？",
    "*Happy Ruff*": "*开心地汪了一声*",
    "You just try and get passed me and this": "有本事就从我和这头",
    "magnificent beast.": "威风凛凛的猛兽身边过去。",
    # Hades confrontation and end credits.
    "I could do with a nice warm cup of...": "真想来一杯热乎乎的……",
    "about my spirits?": "那我手下的游魂怎么办？",
    "Persuade my spirits? You have nerve,": "想劝服我的游魂？你胆子不小，",
    "Persuade my spirits? You have nerve, ": "想劝服我的游魂？你胆子不小，",
    "little one. What, were you going to": "小家伙。怎么，你还打算",
    "little one.": "小家伙。",
    "persuade the walls too?": "连墙壁也一起说服？",
    "What where you going to persuade the": "怎么，你还真打算去说服",
    "walls?": "那些墙？",
    "Clever.. very clever Ri. Pray tell,": "聪明……真聪明，里。不过说来听听，",
    "however, how do you plan to get past me?": "你打算怎么过我这一关？",
    "How unfortunate you are. What is your": "真可惜。里，你最后",
    "final plea, Ri?": "还想求我什么？",
    "Hmm, a valiant effort, but I am already ": "嗯，勇气可嘉，可我已经",
    "relaxed.": "很放松了。",
    "As if that would work on m... Persephone?!": "这招怎么可能对我……珀耳塞福涅？！",
    "Haven't you had enough of this Hades?": "这还不够吗，哈迪斯？",
    "they've gone through this enough my dear.": "他们受的折腾已经够多了，亲爱的。",
    "Ha ha ha ha ha, HA HA HA you!?": "哈哈哈哈，就凭你！？",
    "Grasping at threads now are we? I'll": "病急乱投医了？我就",
    "give you one more chance out of pity.": "发发慈悲，再给你一次机会。",
    "No, I'm sure... I know that I am right,": "不，我很确定……我的决定没错。",
    "I'm sorry Ri. You cannot go.": "抱歉，里。你不能走。",
    "That just makes me more resolute in my": "这反而让我更加坚定",
    "decision.": "自己的决定。",
    "would you get past my walls?": "你打算怎么穿过我的墙？",
    "would you get past my spirits?": "你打算怎么摆脱我手下的游魂？",
    "would you get past my spirits and walls?": "你打算怎么越过我的游魂和墙壁？",
    "Surely, this isn't a suprise, Ri? ": "你不会真觉得意外吧，里？ ",
    "safeguard the Underworld, where all the": "守护冥界，所有死者都",
    "dead reside and where all the dead should": "居于此处，也都应该",
    "stay.": "留在这里。",
    "And so, here I am. The last obtacle\\..\\..\\..": "所以我来了。最后一道障碍\\..\\..\\..",
    "Your last trial.": "你最后的考验。",
    "Prove to me that you are worth letting go.": "证明你值得我放你离开。",
    "Prove to me that you will uphold your end": "证明你会履行",
    "of the deal, Orus.": "我们的约定，奥鲁斯。",
    "Orus, wait for me this time!": "奥鲁斯，这次等等我！",
    "EP: Derek Kwan": "执行制片人：Derek Kwan",
    "Animation Artist: Jenny Lee": "动画师：Jenny Lee",
    "Music Composer: Georgin Maliakal": "作曲：Georgin Maliakal",
    "Trailer Creator: Brandon Fiogbe": "预告片制作：Brandon Fiogbe",
    "Tile and Map Designer: Imtisam Kamaldin-Suleiman": "图块与地图设计：Imtisam Kamaldin-Suleiman",
    "                  Joel Weller": "                  Joel Weller",
    "                  Jenny Lee": "                  Jenny Lee",
    "                        Imtisam Kamaldin-Suleiman": "                        Imtisam Kamaldin-Suleiman",
    "CandyCodedResponse @ https://ccrgeek.wordpress.com/": "CandyCodedResponse @ https://ccrgeek.wordpress.com/",
    "- YEP_SaveEventLocations": "- YEP_SaveEventLocations",
    "- TerraxLighting": "- TerraxLighting",
    "- ShadowDragon_SM": "- ShadowDragon_SM",
    "- lineofsight": "- lineofsight",
    "- GitCompatibilityPatch": "- GitCompatibilityPatch",
    # Labyrinth and bridge dialogue.
    "While the \\.pomegranate\\. is known as the ": "\\.石榴\\.素有",
    "fruit of the dead, \\.it also symbolizes": "“死者之果”之名，\\.却也象征",
    "rebirth \\.and life. ": "重生\\.与生命。 ",
    "And no, I'm not giving you any. These aren't ripe yet.": "别想了，我不会给你的。这些还没熟。",
    "GUARDS!": "卫兵！",
    "\\{GUARDS!\\}": "\\{卫兵！\\}",
    "Oh goody, onwards!": "太好了，出发吧！",
    "You Recieved a \\C[25]Piece of Wood\\C[0]!": "获得了\\C[25]木板\\C[0]！",
    "Word is that none can make it out without": "听说没有多余的木板，就没人能",
    "some extra wood. Best you find some before": "离开这里。你最好先找一些，",
    "moving on. ": "再继续前进。 ",
    "I, Sir Castor, knows best afterall!": "我卡斯托耳爵士最清楚不过了！",
    "I’ve never seen those things before. Every ": "我从没见过那些东西。每次",
    "time one of them sees me, I get sent right ": "被它们发现，我都会被直接",
    "back here. Best not to be seen by them!": "送回这里。最好别让它们看见！",
    "I am searching! For my brother! Castor!": "我在找人！我的哥哥！卡斯托耳！",
    "Have you seen! Him!": "你见过！他吗！",
    "Thank! Goodness! Madam!": "谢天！谢地！女士！",
    "Is that you brother?": "哥哥，是你吗？",
    "Thanks adventurer, I'd give you a reward,": "谢谢你，冒险者。本想给你些报酬，",
    "but not with these outragous taxes.": "可这些离谱的税已经把我掏空了。",
    "You really did a number to the bridge the ": "上次你可把这座桥折腾得不轻，",
    "last time around, Ri.”": "里。",
    "What kind of psycho builds a labyrinth? ": "究竟什么疯子会造这种迷宫？ ",
    "I mean, really?!": "我是说，认真的？！",
    "la di da di da\\{ACK!": "啦哩哒……\\{啊！",
    "Holy Zeus, you’re silent! I assume you’re ": "宙斯在上，你可真沉默！我猜你",
    "here because you want to cross the bridge ": "又是来过桥的，",
    "again?": "对吧？",
    "Well, when I was making my way through the ": "我穿过迷宫时，",
    "labyrinth, I noticed a lot of wood ": "看见到处散落着",
    "scattered around the place.": "不少木板。",
    "I could use those to repair this old thing. ": "那些正好能用来修这座破桥。 ",
    "Oh! Now that's a lot of wood, lets build this ": "哦！这木板够多了，来把这座桥",
    "thing!": "修好吧！",
    "Oh good, you have some wood. Pass it over.": "太好了，你有木板。给我吧。",
    "Dunch'ya think that lava looks like cheese?": "你不觉得那岩浆看着像奶酪吗？",
    "Not this time, miss Ri. But I expect that he has made": "这次没见到，里小姐。不过我想他应该已经",
    "it through this little maze already. He probably has": "走出这个小迷宫了。现在他大概已经",
    "the path memorized by now.": "把路线背熟了。",
    "Go on then, find your Orus.": "快去吧，去找你的奥鲁斯。",
    "My son is up ahead": "我儿子就在前面，",
    "–giant wings–can’t miss him, ": "长着一对巨大的翅膀——一眼就能认出来。",
    "My son, Icarus, is up ahead. ": "我儿子伊卡洛斯就在前面。 ",
    "Giant wings, can’t miss him. ": "长着一对巨大的翅膀，一眼就能认出来。 ",
    "This wall over here is cracked, but I'm not strong": "这边的墙已经裂了，可我力气不够，",
    "enough to break it... ": "砸不开它…… ",
    "YOU! Hey you, can you break it for me? ": "你！那边那位，能帮我砸开吗？ ",
    "\\{*BOOOOOOM*": "\\{*轰——！*",
    "\\{\\{ME\\}OW\\} !": "\\{\\{喵\\}呜\\}！",
    "RI?! What are you doing here?": "里？！你怎么会在这里？",
    "What am I doing? Right, well... I\\..\\..\\..": "我来做什么？这个嘛……我\\..\\..\\..",
    "Yeah, my dog ran off with a ball of thread ": "对，我的狗叼着一团线跑了，",
    "and here I am, cleaning up the mess. ": "我只好来收拾残局。 ",
    "\\{Ou\\{cH! \\}\\}My ears hurt now.": "\\{好\\{痛！\\}\\}我的耳朵都受不了了。",
    "Ugh, that’s powerful. I'd much rather ": "啊，这威力太大了。我还是希望",
    "you play something nicer\\..\\..\\..": "你弹点悦耳的\\..\\..\\..",
    "Actually, I do have something nicer for you.": "其实，我倒有一首更好听的曲子给你。",
    "Before I was trapped in here, of course.": "当然，是在我被困进来以前。",
    "You have recieved \\C[14]Song of Soothing\\C[0]!": "获得了\\C[14]安抚之歌\\C[0]！",
    "Oh! I've heard that there's lava surrounding ": "哦！听说这里的出口被岩浆包围，",
    "the exit to this place. Maybe you can look ": "也许你可以四处找找，",
    "around for objects to help you get across! ": "看有没有东西能帮你过去！ ",
    "I didn’t know you were so cold, Ri.": "没想到你这么冷漠，里。",
    "Take it then\\..\\..\\.. ": "那就拿去吧\\..\\..\\.. ",
    "Leave me.": "别管我。",
    "Oh, and I've heard that there's lava surrounding ": "哦，我还听说这里的出口被岩浆包围，",
    "the exit to this place. Perhaps there are": "也许附近有",
    "some objects that could to help you get across. ": "能帮你过去的东西。 ",
    "You found a \\C[25]Piece of Wood\\C[0]!": "找到了\\C[25]木板\\C[0]！",
    "Zzz...": "呼噜……",
    "wh'achya zzz..": "干什么……呼噜……",
    "Le..ave m\\.e \\.b\\e Zzz": "别..打扰我\\. \\.吧\\e 呼噜",
    # Fields of Asphodel ambient dialogue and directions.
    "but none come out the same.": "但出来时都已经变了样。",
    "\\C[16]<-- River Lethe": "\\C[16]<-- 勒忒河",
    "\\C[5]Hades' Tavern -->": "\\C[5]哈迪斯酒馆 -->",
    "Or use the \\C[24]Mouse\\C[0] for both.": "也可以全程使用\\C[24]鼠标\\C[0]。",
    "He seems\\..\\..\\.. familiar.": "他看起来\\..\\..\\..很眼熟。",
    "\\pop[913]Oh hello, I’m\\..\\..\\.. Wait\\..\\..\\.. ": "\\pop[913]哦，你好，我是\\..\\..\\..等等\\..\\..\\.. ",
    "\\pop[915]Oh hello, I’m\\..\\..\\.. Wait\\..\\..\\.. ": "\\pop[915]哦，你好，我是\\..\\..\\..等等\\..\\..\\.. ",
    "\\pop[913]I c-can’t seem to remember.": "\\pop[913]我、我好像想不起来了。",
    "\\pop[915]I c-can’t seem to remember.": "\\pop[915]我、我好像想不起来了。",
    "\\pop[913]Hessa?\\. Harmonia?\\. Hmm..\\. that’s not it... ": "\\pop[913]赫莎？\\.哈耳摩尼亚？\\.嗯……\\.都不对…… ",
    "\\pop[915]Hessa?\\. Harmonia?\\. Hmm..\\. that’s not it... ": "\\pop[915]赫莎？\\.哈耳摩尼亚？\\.嗯……\\.都不对…… ",
    "Where are you trying to go? \\.Tartarus?": "你想去哪儿？\\.塔耳塔罗斯？",
    "Heck, I’d prefer Tartarus over": "唉，我宁愿去塔耳塔罗斯，",
    "\\..\\..\\.. wherever this is.": "\\..\\..\\..也好过这个鬼地方。",
    "It looked like he was heading towards \\C[5]Hades' Tavern\\c[0].": "他好像往\\C[5]哈迪斯酒馆\\c[0]去了。",
    "Take a moment and humour an old spirit ": "陪我这个老游魂聊两句吧。 ",
    "If you don't know who he is, why do you follow him ": "可你连他是谁都不知道，为什么",
    "every time he comes down here?": "每次他下来时都要跟着他？",
    "over there. \\}*grumble* *grumble*\\{": "那边至少还有点事可做。\\}*嘟囔* *嘟囔*\\{",
    "\\pop[987]You lost it?!": "\\pop[987]你把它弄丢了？！",
    "\\pop[987]My prized flute, you LOST IT?": "\\pop[987]我最宝贝的长笛，你居然弄丢了？！",
    "\\pop[988]I swear I have it…": "\\pop[988]我发誓它还在我手上……",
    "\\pop[988]I just misplaced it somewhere around here": "\\pop[988]我只是忘了放在这附近的什么地方",
    "\\pop[988]Maybe I dropped it.": "\\pop[988]也许是不小心掉了。",
    "He was walking towards \\C[5]Hades' Tavern\\C[0],": "他当时正往\\C[5]哈迪斯酒馆\\C[0]走，",
    "Go away!": "走开！",
    "E-Excuse me!": "打、打扰了！",
    "Hmph. I guess I'll be keeping it then.": "哼。那我就自己留着了。",
    "The water looks so drinkable right now. N-not for you": "这河水看起来真想让人喝一口。不、不是说你",
    "of course, that water is bad for you don't touch it.": "当然，你可不能碰，这水对你有害。",
    # Asphodel Plaza, Minotaur den, and tavern dialogue.
    "Did you take another swim in the \\C[16]River Lethe\\C[0] miss Ri?": "里小姐，你又去\\C[16]勒忒河\\C[0]游泳了吗？",
    "Lethe, \\.heh. Its waters are pretty \\{Lethe\\}-al": "勒忒河，\\.嘿嘿。喝一口，记忆就会\\{一干二净\\}。",
    "to one's memory I'd say.": "我说得没错吧。",
    "hAh\\{ahAH \\}HA Ha ah": "哈\\{哈哈 \\}哈哈哈",
    "I crack myself up.": "我可真幽默。",
    "I am Aion, a pleasure to make your RE-acquaintance.": "我是埃翁，很高兴再次认识你。",
    "h-HEY!": "喂、喂！",
    "WAIT!": "等等！",
    "\\..\\..\\..I wanted to speak with you...": "\\..\\..\\..我还想跟你说话呢……",
    "\\..\\..\\..How rude! I didn't even play anything.": "\\..\\..\\..真没礼貌！我明明什么都没演奏。",
    "\\.Hmph, \\.I'll blow them away with my skills.": "\\.哼，\\.看我露一手，把它们全吹跑。",
    "\\.I'll show them!": "\\.走着瞧！",
    "Someone unusual? D'ya mean mister Orus miss?": "不寻常的人？小姐，你是说奥鲁斯先生吗？",
    "Oh! Well he just passed by. If you head towards": "哦！他刚刚经过。往",
    "\\C[5]Hades' Tavern\\C[0] just over there, to the right,": "右边不远处的\\C[5]哈迪斯酒馆\\C[0]走，",
    "you should be able to catch him.": "你应该还能追上他。",
    "Orus? Well he comes by often, sometimes he even plays": "奥鲁斯？他经常来，有时还会用里拉琴",
    "me songs on his lyre! He had blond hair and w-wears ... ": "给我弹曲子！他一头金发，还、还穿着…… ",
    "green... hey, have we had this conversation before?": "绿色衣服……等等，我们是不是聊过这个？",
    "Shoot.": "糟了。",
    "There are too many spirits here, I can't get through.": "这里的游魂太多，我过不去。",
    "Are you talking about mister Aion over there?": "你是在说那边的埃翁先生吗？",
    "He's pretty weird.": "他挺古怪的。",
    "\\pop[0]BOOOOOOOOOOOO": "\\pop[0]呜呜呜呜呜呜呜呜",
    "It wasn't even that bad!": "也没那么难听吧！",
    "You've collected the Song of Breaking!": "获得了破障之歌！",
    "You found a Davul!": "找到了达武尔鼓！",
    "So loud it can break down some walls!": "鼓声震耳欲聋，甚至能震塌某些墙壁！",
    "Ou DARES to disturb m’rest. ": "谁敢打扰俺睡觉。 ",
    "I’ll give you a reason to never mess ": "我要让你再也不敢来",
    "with me again.": "招惹我。",
    "O-oh, I... my love, my life, my- my WIFE! ": "糟、糟了……我的爱人，我的命，我、我的老婆！ ",
    "I’m late for dinner! Oh she’s going to ": "晚饭要迟到了！她非得",
    "KILL me.": "宰了我不可。",
    "You've aquired \\C[14]Song of Tinder!\\C[0]": "获得了\\C[14]引燃之歌\\C[0]！",
    "Ooh! A lyre. I used to love it when Orus": "哦！一把里拉琴。以前奥鲁斯为我",
    "played it for m\\.\\.e\\..\\..\\.. wait what?": "演奏时，我最喜欢听了\\.\\.\\..\\..\\..等等，什么？",
    "\\.Orus? ": "\\.奥鲁斯？ ",
    "Hello love! Don’t mind him.": "你好，亲爱的！别理他。",
    "He’s actually a real big softie.": "他其实心软得很。",
    "Nothing love! Nothing. \\}*winks*": "没事，亲爱的！真没事。\\}*眨眼*",
    "Sorry about my sister Calliope, she’s spent": "别介意我姐姐卡利俄珀，她跟",
    "far too much time with Narcissus.": "纳耳喀索斯待得太久了。",
    "Narcissus.": "纳耳喀索斯。",
    "Who am I kidding, why wouldn’t you.": "我谦虚什么呢，你当然会喜欢。",
    "My name is Calliope.": "我叫卡利俄珀。",
    "those pesky little spirits \\C[20]scatter\\C[0].": "那些讨厌的小游魂\\C[20]四散而逃\\C[0]。",
    "This, here, is the \\C[14]Song of Tinder\\C[0].": "这就是\\C[14]引燃之歌\\C[0]。",
    "A perfect song for sparking fires!": "最适合用来点燃火焰！",
    "\\.\\.In the hearts of your fans, of course.": "\\.\\.当然，我是说点燃乐迷心中的火焰。",
    "Press \\C[24]Shift\\C[0] at any time to see": "随时按\\C[24]Shift键\\C[0]查看",
    "the notes for each song you collect.": "你已收集曲目的音符。",
    "Why don't you play it right now?": "现在就试着演奏一次吧？",
    "There you go!": "就是这样！",
    "I was about to tell her about the new tapestry I was": "我正要跟她讲我那幅新挂毯，",
    "working on\\..\\..\\..": "还没织完呢\\..\\..\\..",
    "Hmm... I think a light blue string would be perfect ": "嗯……我觉得浅蓝色的线最适合",
    "for my next piece! What do you think Ri?": "下一件作品！里，你觉得呢？",
    "I'm Arachne, at your service!": "我是阿拉克涅，很高兴为你效劳！",
    "Maybe the next time Hermes comes by, you can ask": "下次赫尔墨斯经过时，你可以问问",
    "him about your memory loss.": "他该怎么治你的失忆。",
    "And then he stumbed into\\{ ME! \\} What a rude fella.": "然后他一头撞上了\\{我！\\}真没礼貌。",
    "You can press \\C[24]Escape\\C[0] to cancel.": "按\\C[24]Esc键\\C[0]可以取消。",
    "\\{BO\\}OO! ": "\\{呜\\}呜！ ",
    # West bank and ending hints.
    "So\\..\\..\\.. Karen wants to talk to the manager\\..\\..\\..?": "所以\\..\\..\\..凯伦想见管事的\\..\\..\\..？",
    "And you think that’s me?! ": "你居然觉得那是我？！ ",
    "\\{Ha\\{Ha\\{Ha!": "\\{哈\\{哈\\{哈！",
    "Don’t you worry, I’ll pass on the message ": "别担心，我走之前会替你转告。 ",
    "before I leave.The one and only Hermes is ": "独一无二的赫尔墨斯",
    "at your service!": "为你效劳！",
    "Oh... and Ri?": "哦……对了，里？",
    "He's so close\\..\\..\\..": "他就在附近\\..\\..\\..",
    "You two have been doing this for far too long.": "你们这样周而复始已经太久了。",
    "Long enough for us all to grow weary.": "久到我们所有人都已厌倦。",
    "I await a happy ending.": "我等着看到圆满的结局。",
    "For whatever comes next...": "接下来无论遇到什么……",
    "do things in the order that you see them.": "都按你看见的顺序行动。",
    "Then you'll have to do this yet again. ": "那你只好再来一遍了。 ",
    "Perhaps \\C[27]she\\C[0] will interfere this time.": "也许这次\\C[27]她\\C[0]会出手干预。",
    # Choice labels that are safe to translate globally.
    "Duval": "达武尔鼓",
    "Flute (Song of Soothing)": "长笛（安抚之歌）",
    "Pet the cat?": "摸摸猫？",
    "Again?": "再来一次？",
    "Have you seen anyone... unusual walking through here?": "你有没有见过什么……不同寻常的人经过这里？",
    "Yeah, it’s very smooth, I like it.": "嗯，很顺耳，我喜欢。",
    "Blue is a lovely colour!": "蓝色真好看！",
    "\\{bWHaha\\{HahAh\\}hah\\}a!": "\\{哇哈哈\\{哈哈\\}哈\\}哈！",
    "\\{\\{AA\\}AH\\}HHH! GET AWAY THIEF!": "\\{\\{啊\\}啊\\}啊啊！小偷，滚开！",
    "Zzz\\..\\..\\..": "呼噜\\..\\..\\..",
    "\\.Z\\.z\\.z, Ri?": "\\.呼\\.噜\\.呼，里？",
    "Z\\.z\\.z...": "呼\\.噜\\.呼……",
    "Liberty @ RPGMaker.net": "Liberty @ RPGMaker.net",
    # Skill and state messages are appended to the battler name.
    " guards.": " 进入防御状态。",
    " has fallen!": " 倒下了！",
    " is slain!": " 被击倒了！",
    " revives!": " 复活了！",
    " falls asleep!": " 睡着了！",
    " is sleeping.": " 正在沉睡。",
    " wakes up!": " 醒了！",
    " is poisoned!": " 中毒了！",
    " is no longer poisoned!": " 解除了中毒状态！",
    " is blinded!": " 陷入了失明状态！",
    " is no longer blinded!": " 解除了失明状态！",
    " is silenced!": " 陷入了沉默状态！",
    " is no longer silenced!": " 解除了沉默状态！",
    " is enraged!": " 陷入了狂怒状态！",
    " is no longer enraged!": " 解除了狂怒状态！",
    " is confused!": " 陷入了混乱状态！",
    " is no longer confused!": " 解除了混乱状态！",
    " is fascinated!": " 被迷住了！",
    " is no longer fascinated!": " 解除了着迷状态！",
    # RPG Maker battle and menu messages.
    "%1 was drained of %2 %3!": "%1的%3被吸取了%2点！",
    "%1 gained %2 %3!": "%1的%3增加了%2点！",
    "%1 lost %2 %3!": "%1的%3减少了%2点！",
    "Miss! %1 took no damage!": "未命中！%1没有受到伤害！",
    "%1 recovered %2 %3!": "%1恢复了%2点%3！",
    "%1's %2 went up!": "%1的%2提升了！",
    "%1's %2 returned to normal!": "%1的%2恢复了正常！",
    "%1's %2 went down!": "%1的%2降低了！",
    "%1 counterattacked!": "%1进行了反击！",
    "A painful blow!!": "致命一击！！",
    "An excellent hit!!": "漂亮的一击！！",
    "%1 emerged!": "%1出现了！",
    "To Next %1": "距离下一级还需%1",
    "%1 nullified the magic!": "%1使魔法无效化了！",
    "%1 reflected the magic!": "%1反射了魔法！",
    "%1 %2 received!": "获得了%1 %2！",
    "%1\\G found!": "获得了%1\\G！",
    "%1 found!": "获得了%1！",
    "%1's Party": "%1一行",
    "Possession": "持有数",
    "%1 was victorious!": "%1获得了胜利！",
    # Speaker labels and recurring proper names.
    "[Achilles]": "[阿喀琉斯]",
    "[Aegeus]": "[埃勾斯]",
    "[Aiakos]": "[埃阿科斯]",
    "[Arachne]": "[阿拉克涅]",
    "[Ariadne]": "[阿里阿德涅]",
    "[Ariadne] ": "[阿里阿德涅] ",
    "[Brandon]": "[布兰登]",
    "[Calliope]": "[卡利俄珀]",
    "[Cerberus]": "[刻耳柏洛斯]",
    "[Daedalus]": "[代达罗斯]",
    "[Derek]": "[德里克]",
    "[Euterpe]": "[欧忒耳佩]",
    "[Georgin]": "[乔金]",
    "[Hades]": "[哈迪斯]",
    "[Hephaestus]": "[赫淮斯托斯]",
    "[Hercules]": "[赫拉克勒斯]",
    "[Hermes]": "[赫尔墨斯]",
    "[Hippolyta]": "[希波吕忒]",
    "[Icarus]": "[伊卡洛斯]",
    "[Imtisam]": "[伊姆蒂萨姆]",
    "[Jason]": "[伊阿宋]",
    "[Jenny]": "[珍妮]",
    "[Joel]": "[乔尔]",
    "[Karen]": "[凯伦]",
    "[Medusa]": "[美杜莎]",
    "[Meta]": "[梅塔]",
    "[Minotaur]": "[弥诺陶洛斯]",
    "[Muse]": "[缪斯]",
    "[Nyx]": "[倪克斯]",
    "[Odysseus]": "[奥德修斯]",
    "[Orus]": "[奥鲁斯]",
    "[Parham] ": "[帕尔哈姆] ",
    "[Patroclus]": "[帕特洛克罗斯]",
    "[Pegasus]": "[珀伽索斯]",
    "[Persephone]": "[珀耳塞福涅]",
    "[Perseus]": "[珀尔修斯]",
    "[Pollux]": "[波吕克斯]",
    "[Sir Castor]": "[卡斯托耳爵士]",
    "[Theseus]": "[忒修斯]",
    "[\\C[1]Ri\\C[0]]": "[\\C[1]里\\C[0]]",
    "[\\C[27]Persephone\\C[0]]": "[\\C[27]珀耳塞福涅\\C[0]]",
    "[\\C[31]Minotaur\\C[0]]": "[\\C[31]弥诺陶洛斯\\C[0]]",
    "\\C[1]Ri\\C[0]": "\\C[1]里\\C[0]",
    "{\\C[1]Ri\\C[0]]": "{\\C[1]里\\C[0]]",
    # Blackjack common event terminology.
    "Game Start!": "牌局开始！",
    "Player Start!": "玩家回合！",
    "Dealer: Ace!": "庄家：A牌！",
    "Dealer: \\v[1]": "庄家：\\v[1]",
    "Player Card 1: Ace": "玩家第1张牌：A",
    "Player Card 1: \\v[3]": "玩家第1张牌：\\v[3]",
    "Player Card 2: Ace": "玩家第2张牌：A",
    "Player Card 2: \\v[4]": "玩家第2张牌：\\v[4]",
    "Player Card 3: Ace": "玩家第3张牌：A",
    "Player Card 4: Ace": "玩家第4张牌：A",
    "Player Card 5: Ace": "玩家第5张牌：A",
    "Player total: \\v[3]": "玩家点数：\\v[3]",
    "Hit or Hold?": "要牌还是停牌？",
    "Hit": "命中率",
    "Hold": "停牌",
    "Blackjack! Player wins!": "二十一点！玩家获胜！",
    "Player busts, you lose.": "玩家爆牌，本局失败。",
    "Player turn end.": "玩家回合结束。",
    "Dealer Continues.": "庄家继续要牌。",
    "Ace!": "A牌！",
    "Blackjack Dealer total: \\v[1]": "庄家点数：\\v[1]",
    "Blackjack Dealer total: \\v[2]": "庄家点数：\\v[2]",
    "Dealer Card 3: Ace": "庄家第3张牌：A",
    "Dealer Card 4: Ace": "庄家第4张牌：A",
    "Dealer Card 5: Ace": "庄家第5张牌：A",
    "Dealer busts, Player wins!": "庄家爆牌，玩家获胜！",
    "Player loses.": "玩家失败。",
    "Draw!": "平局！",
    "Player has 5 cards, Player wins!": "玩家凑齐5张牌，玩家获胜！",
    "Blackjack Dealer Pushes": "庄家与玩家和局",
    "Player wins.": "玩家获胜。",
    # Song feedback and names.
    "Song of Soothing": "安抚之歌",
    "Song of Tinder": "引燃之歌",
    'Congrats, you played "\\c[14]Song of Soothing\\c[0]"': "演奏成功：\\c[14]安抚之歌\\c[0]",
    'Congrats, you played "\\c[14]Song of Breaking\\c[0]"': "演奏成功：\\c[14]破障之歌\\c[0]",
    'Congrats, you played "\\c[14]Song of Persuasion\\c[0]"': "演奏成功：\\c[14]劝服之歌\\c[0]",
    'Congrats, you played "\\c[14]Song of Tinder\\c[0]"': "演奏成功：\\c[14]引燃之歌\\c[0]",
    "That was horrible!": "太难听了！",
}

NAME_REPLACEMENTS = {
    "Narcissus": "纳耳喀索斯",
    "Persephone": "珀耳塞福涅",
    "Hephaestus": "赫淮斯托斯",
    "Patroclus": "帕特洛克罗斯",
    "Hippolyta": "希波吕忒",
    "Odysseus": "奥德修斯",
    "Achilles": "阿喀琉斯",
    "Calliope": "卡利俄珀",
    "Cerberus": "刻耳柏洛斯",
    "Minotaur": "弥诺陶洛斯",
    "Daedalus": "代达罗斯",
    "Ariadne": "阿里阿德涅",
    "Hercules": "赫拉克勒斯",
    "Arachne": "阿拉克涅",
    "Euterpe": "欧忒耳佩",
    "Perseus": "珀尔修斯",
    "Pegasus": "珀伽索斯",
    "Theseus": "忒修斯",
    "Aiakos": "埃阿科斯",
    "Aegeus": "埃勾斯",
    "Icarus": "伊卡洛斯",
    "Hermes": "赫尔墨斯",
    "Medusa": "美杜莎",
    "Pollux": "波吕克斯",
    "Hades": "哈迪斯",
    "Jason": "伊阿宋",
    "Orus": "奥鲁斯",
    "Nyx": "倪克斯",
    "Muse": "缪斯",
    "Aion": "埃翁",
    "Tartarus": "塔耳塔罗斯",
    "Lethe": "勒忒",
    "Ri": "里",
}

CHINESE_NAME_NORMALIZATION = {
    "卡莉奥佩": "卡利俄珀",
    "爱马仕": "赫尔墨斯",
    "爱斯福德尔": "阿斯福德尔",
}

CREDIT_MARKERS = (
    "Artist:",
    "Composer:",
    "Creator:",
    "Designer:",
    "EP:",
    "Programmer",
    "Producer:",
    "RPGMaker.net",
    "wordpress.com",
)

ASCII_WORD = re.compile(r"[A-Za-z]{2,}")
CONTROL_CODE = re.compile(r"\\(?:[A-Za-z]+(?:\[[^\]]*\])?|[.!{}])")
INTENTIONAL_LATIN_TERMS = {"HP", "MP", "TP", "Max MP"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_names(source: str, target: str) -> str:
    if any(marker in source for marker in CREDIT_MARKERS):
        return target
    result = target
    for name, translated in sorted(NAME_REPLACEMENTS.items(), key=lambda item: -len(item[0])):
        result = re.sub(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", translated, result)
    for current, preferred in CHINESE_NAME_NORMALIZATION.items():
        result = result.replace(current, preferred)
    return result


def _contains_visible_ascii(text: str) -> bool:
    return ASCII_WORD.search(CONTROL_CODE.sub("", text)) is not None


def _intentional_latin(source: str) -> bool:
    return (
        source in INTENTIONAL_LATIN_TERMS
        or source[:1].isspace()
        or any(marker in source for marker in CREDIT_MARKERS)
        or source.startswith("- ")
        or " @ " in source
        or "http://" in source
        or "https://" in source
        or "RPGMaker" in source
        or "\\C[24]Escape\\C[0]" in source
        or "\\C[24]Shift\\C[0]" in source
    )


def refine(dictionary: dict[str, str]) -> tuple[dict[str, str], dict[str, object]]:
    missing = sorted(set(EXACT_OVERRIDES) - set(dictionary))
    if missing:
        raise ValueError(f"override source text is absent from v2 dictionary: {missing}")
    refined = {
        source: _replace_names(source, EXACT_OVERRIDES.get(source, target))
        for source, target in dictionary.items()
    }
    changed = sorted(source for source in refined if refined[source] != dictionary[source])
    residual = [
        {"source_text": source, "target_text": target}
        for source, target in refined.items()
        if _contains_visible_ascii(target)
    ]
    intentional_latin = [
        item for item in residual if _intentional_latin(item["source_text"])
    ]
    review_required_ascii = [
        item for item in residual if not _intentional_latin(item["source_text"])
    ]
    unchanged = [
        {"source_text": source, "target_text": target}
        for source, target in refined.items()
        if source == target
    ]
    report = {
        "schema_version": "hanengine.project-text-quality-audit/v1",
        "dictionary_entries": len(dictionary),
        "changed_entries": len(changed),
        "changed_source_texts": changed,
        "target_ascii_word_entries": residual,
        "intentional_latin_entries": intentional_latin,
        "review_required_ascii_entries": review_required_ascii,
        "source_equals_target_entries": unchanged,
    }
    return refined, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply reviewed Hello Underworld terminology and UI corrections."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if _sha256(source) != EXPECTED_INPUT_SHA256:
        raise ValueError("source dictionary does not match the reviewed v2 input")
    dictionary = json.loads(source.read_text(encoding="utf-8"))
    refined, report = refine(dictionary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(refined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Dictionary: {args.output.resolve()}")
    print(f"Audit report: {args.report.resolve()}")
    print(f"Changed entries: {report['changed_entries']}")
    print(f"Target ASCII word entries: {len(report['target_ascii_word_entries'])}")
    print(
        "Review-required ASCII entries: "
        f"{len(report['review_required_ascii_entries'])}"
    )
    print(f"Source equals target entries: {len(report['source_equals_target_entries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
