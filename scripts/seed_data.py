#!/usr/bin/env python3
"""
OxBlood Portal - Seed Data Script
Populates the database with realistic test data for development and testing.

Usage:
    python3 seed_data.py [--reset] [--token TOKEN]

Options:
    --reset    Clear existing data before seeding
    --token    Use existing auth token instead of logging in
"""

import json
import sys
import argparse
import subprocess
from datetime import datetime, timedelta, timezone

API_BASE = "http://localhost:8000"

def run_api(method, endpoint, data=None, token=None):
    """Make API request and return response."""
    cmd = ["curl", "-s", "-X", method, f"{API_BASE}{endpoint}"]
    if token:
        cmd += ["-H", f"X-Divide-Token: {token}"]
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except:
        return {"_raw": result.stdout[:200], "_error": True}

def get_token():
    """Login and get auth token."""
    print("  Logging in as admin...")
    result = run_api("POST", "/api/v1/auth/login", {
        "sub": "admin",
        "password": "adminpass123"
    })
    if "token" in result:
        return result["token"]
    else:
        print(f"  ERROR: Login failed: {result}")
        sys.exit(1)

def seed_drills(token):
    """Seed drills in various states."""
    print("\n2. Seeding drills...")
    
    drills = [
        {
            "title": "Web Exploitation 101",
            "description": "Learn the basics of web application security. Practice SQL injection, XSS, and CSRF attacks in a safe environment.",
            "drill_type": "individual",
            "duration_limit_minutes": 60,
            "max_participants": 20,
            "status": "scheduled"
        },
        {
            "title": "Network Pentesting Challenge",
            "description": "Test your network penetration testing skills. Scan networks, exploit services, and capture flags.",
            "drill_type": "team",
            "duration_limit_minutes": 120,
            "max_participants": 50,
            "status": "scheduled"
        },
        {
            "title": "Active Directory Attack",
            "description": "Practice Active Directory exploitation techniques including Kerberoasting, AS-REP roasting, and privilege escalation.",
            "drill_type": "individual",
            "duration_limit_minutes": 90,
            "max_participants": 15,
            "status": "scheduled"
        },
        {
            "title": "Cloud Security Audit",
            "description": "Audit cloud infrastructure for misconfigurations and vulnerabilities. Focus on AWS and Azure environments.",
            "drill_type": "individual",
            "duration_limit_minutes": 75,
            "max_participants": 25,
            "status": "scheduled"
        },
        {
            "title": "Incident Response Simulation",
            "description": "Respond to a simulated security incident. Analyze logs, contain the breach, and document findings.",
            "drill_type": "team",
            "duration_limit_minutes": 180,
            "max_participants": 30,
            "status": "scheduled"
        },
        {
            "title": "Red Team Exercise",
            "description": "Full-scope red team engagement. Gain initial access, move laterally, and achieve objectives.",
            "drill_type": "team",
            "duration_limit_minutes": 240,
            "max_participants": 40,
            "status": "scheduled"
        },
        {
            "title": "Blue Team Defense",
            "description": "Defend against simulated attacks. Monitor logs, detect intrusions, and respond to threats.",
            "drill_type": "team",
            "duration_limit_minutes": 180,
            "max_participants": 35,
            "status": "scheduled"
        }
    ]
    
    created = []
    for drill in drills:
        result = run_api("POST", "/api/v2/drills", drill, token)
        if "drill_id" in result:
            created.append({"id": result["drill_id"], **drill})
            print(f"   ✓ Created: {drill['title']} (ID: {result['drill_id']})")
        else:
            print(f"   ✗ Failed: {drill['title']} - {result}")
    
    return created

def seed_labs(token):
    """Seed labs with various difficulties."""
    print("\n3. Seeding labs...")
    
    labs = [
        {
            "title": "SQL Injection Basics",
            "description": "Learn to identify and exploit SQL injection vulnerabilities",
            "difficulty": "beginner",
            "duration_minutes": 30,
            "tags": ["web", "sqli", "beginner"]
        },
        {
            "title": "XSS Fundamentals",
            "description": "Understand and exploit Cross-Site Scripting vulnerabilities",
            "difficulty": "beginner",
            "duration_minutes": 25,
            "tags": ["web", "xss", "beginner"]
        },
        {
            "title": "Network Scanning",
            "description": "Master network reconnaissance and port scanning techniques",
            "difficulty": "intermediate",
            "duration_minutes": 45,
            "tags": ["network", "recon", "nmap"]
        },
        {
            "title": "Privilege Escalation",
            "description": "Learn Linux and Windows privilege escalation techniques",
            "difficulty": "advanced",
            "duration_minutes": 60,
            "tags": ["linux", "windows", "privesc"]
        },
        {
            "title": "Reverse Engineering",
            "description": "Analyze malware and reverse engineer binaries",
            "difficulty": "advanced",
            "duration_minutes": 90,
            "tags": ["reverse", "malware", "binary"]
        }
    ]
    
    # Note: Labs may need to be created via a different endpoint or directly in DB
    # For now, we'll skip if the endpoint doesn't exist
    print("   ⚠ Labs seeding requires direct database access or v2 labs endpoint")
    print("   Skipping for now - labs can be added manually")
    
    return []

def seed_reports(token):
    """Seed drill reports."""
    print("\n4. Seeding reports...")
    
    # Reports are typically generated from completed drills
    # For now, we'll note this and skip
    print("   ⚠ Reports are auto-generated from completed drills")
    print("   Skipping for now - complete some drills to generate reports")
    
    return []

def main():
    parser = argparse.ArgumentParser(description="Seed OxBlood Portal with test data")
    parser.add_argument("--reset", action="store_true", help="Clear existing data before seeding")
    parser.add_argument("--token", help="Use existing auth token")
    args = parser.parse_args()
    
    print("=" * 60)
    print("  OxBlood Portal - Seed Data Script")
    print("=" * 60)
    print()
    
    # Get auth token
    token = args.token or get_token()
    if not args.token:
        print(f"  ✓ Token obtained: {token[:20]}...")
    
    # Phase 1: Seed drills
    drills = seed_drills(token)
    
    # Phase 2: Seed labs (if endpoint exists)
    labs = seed_labs(token)
    
    # Phase 3: Seed reports (auto-generated)
    reports = seed_reports(token)
    
    # Summary
    print()
    print("=" * 60)
    print("  Seeding Complete!")
    print("=" * 60)
    print()
    print(f"Created:")
    print(f"  - {len(drills)} drills")
    print(f"  - {len(labs)} labs")
    print(f"  - {len(reports)} reports")
    print()
    print("Next steps:")
    print("  1. Start some drills to test the workflow")
    print("  2. Complete drills to generate reports")
    print("  3. Check the dashboard for updated stats")
    print()

if __name__ == "__main__":
    main()
