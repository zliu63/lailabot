帮我一起设计一个产品，我叫它lailabot

lailabot本质上是claude code的一个封装

lailabot运行在我本地的电脑里面，它与telegram集成，使得我可以通过在telegram创建一个chatbot，然后通过telegram与lailabot对话。

当我在telegram上面跟它表明我想在某个目录启动claude code的时候，它就能替我在该目录下启动claude code

当claude code启动之后，原本的lailabot就变成了一个几乎是透明的claude code的传声筒。我在telegram说的话，会直接透传到claude code里面。claude code的response也会被直接透传到telegram里面

当我跟lailabot说关闭claude code的时候，它就能帮我真的结束claude code的进程。

一些额外的想法：
我可以通过telegram bot的slash command功能给lailabot定义一些commands

比如：
ls: 相当于lailabot在当前运行的路面下面调用了linux command “ls”

start {dir path: a relative or absolute path}: 这个command就是告诉lailabot帮我在要在这个{dir path}下面运行claude code

list：For every created claude code session, lailabot will give the session an ID(numeric id starting from 1). The command will list all the sessions and their IDs. Their will be a default session ID. Basically every message I sent from telegram will be passed to that default session. The default session ID will be marked.

kill {session id}: kill the corresponding claude code session

set_default {session id}: This can help me switch between different claude code sessions.