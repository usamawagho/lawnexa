# LawNexa Bundle Package v7.0 (With Dynamic Legal Document Generator)

Is package me **Dynamic Legal Document Generator** aur **Auth Modal Toggle Tabs (Sign In vs Register)** implement kar diye gaye hain.

## Key Features Added:
1. **Dynamic Legal Document Generator**:
   - Navigation bar me **Legal Documents** tab (`#docgen-tab`).
   - 5 Standard Legal Templates:
     - Kiraya Nama (Rent Agreement)
     - Vehicle Sale Agreement
     - Bail Application (Section 497 CrPC)
     - Cheque Bounce Legal Notice (Section 489-F PPC)
     - Vakalatnama
   - Real-time side-by-side stamp-paper styled live document preview.
   - **Print / PDF Download** capability (`window.print()` with clean CSS print media query).
   - **Save to Account** endpoint (`POST /api/documents/save`).
2. **Auth Modal Toggle Tabs**:
   - Modal ke top par **Sign In** aur **Create Account** ke tabs.
   - Default Mode: Sign In (Sirf Email & Password).
   - Switching to Create Account reveals Full Name, Phone, Address, Role Selector, aur Lawyer details.
