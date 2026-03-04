🚀 Odoo Error Bot
A powerful Telegram bot for managing and searching Odoo error solutions with OCR support. Built with Python, this bot helps Odoo developers and users quickly find solutions to common errors and contribute their own fixes to the community database.

✨ Features
📝 Error Management
Add Solutions: Post new error solutions with detailed descriptions

Text Mode: Manually type error messages, descriptions, and solutions

Image Mode: Upload screenshots - OCR automatically extracts error text

Search Database: Find solutions using keywords or natural language

Recent Solutions: View the latest 5 solutions added to the database

🖼️ OCR Capabilities
Automatic Text Extraction: Extracts text from error screenshots

Multiple OCR Configurations: Tries different recognition modes for accuracy

Image Enhancement: Auto-resizes and enhances images for better text detection

Smart Search: Uses OCR text to automatically search for matching solutions

👥 User Features
Persistent Storage: Remembers users even after clearing chat history

User Statistics: Tracks contributions and activity

📊 Database
SQLite Storage: Lightweight, portable database

Structured Data: Stores error messages, descriptions, and solutions

Timestamp Tracking: Records when solutions are added

Full-Text Search: Case-insensitive search across all fields

🛠️ Commands
Command	Description	Example
/post	Add a new error solution	/post
/search <keyword>	Search for solutions	/search database error
