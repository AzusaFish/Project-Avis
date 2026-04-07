import http.server
import socketserver
import json
import os
import base64
import webbrowser

PORT = 8000
DATA_FILE = "avis_vision.json"
IMAGE_SAVE_DIR = "training_images"

os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>Avis VLM Annotator (Pure Text)</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 20px auto; padding: 20px; background-color: #f4f4f9;}
        .container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h2 { color: #333; text-align: center;}
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input[type="text"], textarea { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        textarea { height: 120px; resize: vertical; }
        img { max-width: 100%; max-height: 300px; margin-top: 10px; border-radius: 4px; display: none; }
        button { background-color: #4a69bd; color: white; border: none; padding: 10px 20px; font-size: 16px; border-radius: 4px; cursor: pointer; width: 100%;}
        button:hover { background-color: #1e3799; }
        #status { margin-top: 15px; text-align: center; color: green; font-weight: bold;}
    </style>
</head>
<body>
    <div class="container">
        <h2>Avis Vision Dataset Builder</h2>
        
        <div class="form-group">
            <label>1. Upload Image:</label>
            <input type="file" id="imageInput" accept="image/*">
            <img id="preview" src="" alt="Preview">
        </div>

        <div class="form-group">
            <label>2. User Prompt (English):</label>
            <input type="text" id="userInput" value="<image>Take a look at this. What do you think?">
        </div>

        <div class="form-group">
            <label>3. Avis Tsundere Response (Plain English Text):</label>
            <textarea id="assistantInput" placeholder="Hmph, did you really interrupt my background processing just to show me this? The collar is so poorly drawn... but I guess the red hood is somewhat acceptable."></textarea>
        </div>

        <button onclick="submitData()">Save to Dataset</button>
        <div id="status"></div>
    </div>

    <script>
        const imageInput = document.getElementById('imageInput');
        const preview = document.getElementById('preview');
        let imageBase64 = null;
        let imageFileName = null;

        imageInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (!file) return;
            imageFileName = file.name;
            const reader = new FileReader();
            reader.onload = function(event) {
                preview.src = event.target.result;
                preview.style.display = 'block';
                imageBase64 = event.target.result.split(',')[1];
            };
            reader.readAsDataURL(file);
        });

        async function submitData() {
            if (!imageBase64) {
                alert("Please select an image first.");
                return;
            }
            
            const userInput = document.getElementById('userInput').value;
            const assistantText = document.getElementById('assistantInput').value;

            if (!assistantText.trim()) {
                alert("Response cannot be empty.");
                return;
            }

            const payload = {
                image_name: imageFileName,
                image_data: imageBase64,
                user_input: userInput,
                assistant_text: assistantText
            };

            const response = await fetch('/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                document.getElementById('status').innerText = "Data saved successfully to avis_vision.json!";
                setTimeout(() => document.getElementById('status').innerText = "", 3000);
                document.getElementById('assistantInput').value = "";
            } else {
                alert("Failed to save data. Check terminal.");
            }
        }
    </script>
</body>
</html>
"""

class SimpleHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/save':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))

            image_path = os.path.join(IMAGE_SAVE_DIR, data['image_name'])
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(data['image_data']))
            
            abs_image_path = os.path.abspath(image_path).replace("\\", "/")

            new_entry = {
                "messages": [
                    {
                        "role": "user",
                        "content": data['user_input']
                    },
                    {
                        "role": "assistant",
                        "content": data['assistant_text']
                    }
                ],
                "images": [abs_image_path]
            }

            existing_data = []
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    try:
                        existing_data = json.load(f)
                    except json.JSONDecodeError:
                        existing_data = []
            
            existing_data.append(new_entry)

            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)

            self.send_response(200)
            self.end_headers()

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), SimpleHandler) as httpd:
        print(f"Annotator running. Open browser at: http://127.0.0.1:{PORT}")
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        httpd.serve_forever()