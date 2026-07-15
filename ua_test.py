from ua_parser import user_agent_parser

ua = input("input now")

result = user_agent_parser.Parse(ua)

print("\n========== Parsed Result ==========")
print("\nBrowser")
print(result["user_agent"])

print("\nOperating System")
print(result["os"])

print("\nDevice")
print(result["device"])
