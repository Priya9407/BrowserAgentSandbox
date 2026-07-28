import os
import re

TEST_PAGES_DIR = r"c:\Nexiva\Frontier\version1\test-pages"

for filename in os.listdir(TEST_PAGES_DIR):
    if not filename.endswith(".html"):
        continue
        
    filepath = os.path.join(TEST_PAGES_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Replace <button> or <button ...> (without onclick) with one having onclick
    # A bit tricky with regex, we can just do specific replacements
    
    # We want to add visual feedback when ANYTHING is clicked (buttons, inputs)
    # But just adding a global click listener to the body is much easier!
    
    if "GLOBAL CLICK LISTENER" not in content:
        script = """
<!-- GLOBAL CLICK LISTENER FOR VISUAL FEEDBACK -->
<script>
  document.addEventListener('click', function(e) {
    if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A' || e.target.type === 'submit') {
      if (!e.target.getAttribute('onclick')) {
         alert('Action Executed: ' + (e.target.innerText || e.target.value || 'Element') + ' ✅');
      }
    }
  });
</script>
</body>
"""
        content = content.replace("</body>", script)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {filename}")
