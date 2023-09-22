# ooba-discord-rp-chatbot
This is a discord bot that uses [oobabooga's text-generation-webui](https://github.com/oobabooga/text-generation-webui) as a backend to load a Large Language Model!

It loads character prompts from files and uses those character prompts to roleplay as those characters, generating responses for entertainment purposes. The characters will remember the most recent conversations that it has had and will be able to carry on a conversation based on that history, but each channel that this bot is in will have a separate chat history (and keep in mind that the person hosting the chatbot may be able to see your conversations, even in private DMs). More than one character can be activated per channel.

The chatbot currently assumes settings and models will be calibrated in the webui's backend.

This chatbot was written by Cadaeic, starting out as an edit to mercm8's fork of [chat-llama-discord-bot](https://github.com/mercm8/chat-llama-discord-bot), and will be under an open source license like MIT or AGPL (TODO). Some presets have been edited from [SillyTavern](https://github.com/SillyTavern/SillyTavern).

## Instructions
WIP instructions:
1. Download [oobabooga's text-generation-webui](https://github.com/oobabooga/text-generation-webui) and at least one model, and run the webui with the --api flag, making sure to set up the model
2. Grab a discord bot token from the Discord Developer Portal with the following permissions: bot, send messages, send messages in threads, read messages/view channels, read message history, use slash commands
3. Put the discord bot token into ``config.yaml``
4. Run this bot with ``python discordbot.py`` in another terminal

## To Do
- Gracefully detect lack of api or model
- easy bat file for installation and running
- possibly accept other backends?
- other example characters that aren't meme napoleon
