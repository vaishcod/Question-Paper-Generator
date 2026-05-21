🏛️ AI-Powered College Question Paper Generator

An enterprise-grade academic assessment platform designed for universities and higher education institutions. The system enables faculty members to securely upload course syllabi and generate well-structured, syllabus-aligned examination papers using advanced AI.

Built with modern web technologies and powered by Gemini 2.5 Flash via OpenRouter, the platform streamlines the traditionally time-consuming process of question paper creation while maintaining academic standards, syllabus coverage, and examination integrity.


🌐 Live Demo

🔗 Application URL
https://question-paper-generator-ivory.vercel.app/upload


✨ Core Features

🤖 AI-Driven Question Paper Generation

* Integrated with **Gemini 2.5 Flash** through the OpenRouter API
* Generates academically structured question papers within seconds
* Produces balanced questions aligned with university examination standards
* Supports customizable prompts and API configurations

📚 Smart Syllabus Processing

* Upload syllabi in:

  * PDF (`.pdf`)
  * Microsoft Word (`.doc`, `.docx`)
* Automatically extracts and processes syllabus content
* Ensures generated questions remain relevant to uploaded curriculum

## 🎯 Advanced Exam Configuration

Customize examination papers using:

* Difficulty levels:

  * Easy
  * Medium
  * Hard
* Examination types:

  * Mid-Term
  * End-Semester
* Target marks distribution
* Unit-wise syllabus coverage
* Section formatting and structure

📝 Interactive Workspace Editor

* Full-screen rich text editor
* Real-time editing capabilities
* Version history and restoration support
* Faculty-friendly workflow for reviewing and refining generated papers

📥 Professional Export Options

Export finalized papers instantly in:

* DOCX format for institutional editing
* High-quality academic PDF format for printing and distribution

🔐 Secure Role-Based Access Control

Authentication and authorization powered by Firebase:

* **Admin** – System management and oversight
* **Dean** – Academic supervision and approvals
* **Faculty** – Question paper generation and editing

☁️ Modern Cloud Deployment

* Frontend hosted on Vercel
* Secure Firebase Authentication integration
* Scalable backend architecture
* Environment-based configuration management


🛠️ Technology Stack

| Category        | Technologies                     |
| --------------- | -------------------------------- |
| Frontend        | HTML, CSS, JavaScript, Bootstrap |
| Backend         | Python, Flask                    |
| AI Integration  | Gemini 2.5 Flash, OpenRouter API |
| Authentication  | Firebase Authentication          |
| File Processing | PDF & DOCX Parsers               |
| Deployment      | Vercel                           |


📁 Project Structure

```bash
QUESTION-PAPER-GENERATOR/
│
├── static/                     # CSS, JS, Assets
├── templates/                  # HTML Templates
├── uploads/                    # Uploaded syllabus files
├── generated_papers/           # Generated output documents
├── firebase_service_account.json
├── requirements.txt
├── .env
├── main.py
└── README.md
```



⚙️ Local Development Setup

  1️⃣ Clone the Repository

```bash
git clone <repository-url>
cd QUESTION-PAPER-GENERATOR
```

2️⃣ Create Virtual Environment

Windows

```bash
python -m venv venv
venv\Scripts\activate
```

macOS/Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

---

3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

---

4️⃣ Configure Firebase Credentials

Place your Firebase Admin SDK JSON file in the project root:

```bash
firebase_service_account.json
```

---

5️⃣ Configure Environment Variables

Create a `.env` file in the root directory:

```env
OPENROUTER_API_KEY=your_openrouter_api_key
FIREBASE_API_KEY=your_firebase_web_api_key
```

---

6️⃣ Start the Application

```bash
python main.py
```

Application will run locally at:

```bash
http://127.0.0.1:5000
```


🔒 Security & Best Practices

* Secure Firebase authentication and authorization
* Environment variable-based secret management
* Role-based access control for institutional workflows
* File upload validation for supported formats only
* Separation of frontend and backend configurations


📌 Use Cases

This platform is ideal for:

* Universities
* Colleges
* Examination departments
* Academic coordinators
* Faculty members preparing semester assessments


🚀 Future Enhancements

Planned improvements include:

* Bloom’s Taxonomy-based question generation
* Multi-language support
* Automated plagiarism checking
* Institutional templates and branding
* AI-assisted marking schemes and answer keys
* Analytics dashboard for syllabus coverage insights




