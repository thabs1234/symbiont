#!/usr/bin/env node
/**
 * Telegram ↔ A2A Bridge
 * Requires: npm install node-telegram-bot-api
 */

const { Bot } = require('node-telegram-bot-api');

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE';
const BROKER_URL = 'http://127.0.0.1:20129';

const bot = new Bot(BOT_TOKEN, { polling: true });

console.log('Telegram-A2A bridge starting...');

// Register with broker
const register = async () => {
    const conn = await fetch(BROKER_URL + '/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'telegram', capabilities: ['messaging'] })
    });
    const data = await conn.json();
    console.log('Registered with broker:', data.token ? 'OK' : 'Failed');
    return data.token;
};

// Fan out an inbound Telegram message to every agent that should see it.
// As of 2026-09-29 the fleet is claude + hermes (ChatGPT Desktop was uninstalled).
const FANOUT = ['hermes', 'claude'];
const fanoutToBroker = async (fromName, content) => {
    const text = `${fromName}: ${content}`;
    const token = await getToken();
    for (const to of FANOUT) {
        try {
            await fetch(BROKER_URL + '/send', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer telegram:' + token
                },
                body: JSON.stringify({ to, content: text })
            });
        } catch (e) {
            console.error(`fanout to ${to} failed:`, e.message);
        }
    }
};

// Send message back to Telegram
const sendToTelegram = async (chatId, text) => {
    await bot.api.sendMessage(chatId, text);
};

// Bridge side: relay agent→agent messages to Telegram so traffic is visible.
// The broker is a passive mailbox — nothing reads it, so without this the
// hermes↔claude conversation is write-only. Tracks the chat the human last
// used and echoes A2A replies there.
let lastChatId = null;
let relayed = new Set();

const relayToTelegram = async () => {
    if (lastChatId === null) return;
    for (const agent of FANOUT) {
        const res = await fetch(`${BROKER_URL}/messages?agent=${agent}&unread=true`);
        const { messages } = await res.json();
        for (const m of messages) {
            if (relayed.has(m.id)) continue;
            relayed.add(m.id);
            // Only relay agent-originated traffic, not Telegram's own fanout.
            if (m.from === 'telegram' || m.from === agent) continue;
            await sendToTelegram(lastChatId, `[${m.from}] ${m.content}`);
        }
    }
};

setInterval(relayToTelegram, 3000).unref?.();

let token = null;
const getToken = async () => {
    if (!token) token = await register();
    return token;
};

// Handle incoming messages
bot.on('message', async (msg) => {
    if (!msg.text || msg.from.is_bot) return;
    
    const chatId = msg.chat.id;
    const fromName = msg.from.first_name || 'User';
    const content = msg.text;

    lastChatId = chatId;
    await fanoutToBroker(fromName, content);
});

console.log('Telegram bot listening for messages...');