import json
import os
from pathlib import Path

# Essential Auth Data extracted from browser
EDEN_AUTH_TOKENS = "TWz7y5uj7Q8HxZ5P32wqy6/lFaDbTi3AAB0z+D480Y0=.WGjH9mdwxkunOFWsm3i5iCGexNPvTpjxgLyFYC9WnRGY3TRazYL+vw8QpFtr1jmQMo3QPzy/j0MdoiRqdo7r4huZe9ExSJmUuBjYgq+AtY6WugZJLsdIG27znyrgCAVTPz6DFopQCTVbSbsJIPg53AhvMVw4VNZk96QFKMVxjW1+enOuaYXlSGiK6YdY4tkK8SvNXAZ2BvbCcnrJraaT92ByHvNthu48zC8a2xPt5pMwNUEt0dl2UX1QfPA5S4yIe/fYcIvtgiA2d33tt97NkLoN14gBaczmsLZJTZRIZijIxHKw8CuPqHWtlCG2mo68bBS9jKqXNmuQLclD8EkLCjrlbxSQYCvvnxafdRu6CNJasQM/boLFDfcQoDzuNOlRu62E8m/JQp5pEsTKP8Mm5E0jHajQtokdEQydZRVDP8UfMIfpMqBGER9k4IaU9Xd8ukJ6Ld3+yz7Jq7NmtMFmqL7V9Fc1MgAnbcu11XOPjVE3bP/ImYFsJslQ66HpJuLDA8u/Q2egOEjzMVy1zHXgVixjGdbSbGTGo94FhwUmLUmFbv8m8ZIEGBCrBGyyzCLWKoGxrjP+h+BJbJQyG9ywEroUO1YmcCQ555p/6hHQGC7RC56IfvppLkSbA1CsFPH2nEWPt0YodePTuYwVV2eiWK788A0gsqKh91sgessl+2KNOYhkRYlQk73wciS3GFzdiq9mrFoEoDbvkpQYQ6oHOY63RVRiLZLpflX4sk4RmcahzocjqWAOYtIK+6O1qeVlYzm/jhkHvFa7b1ptF2lwo0+cdX2CPhSqTTjx93oCjHCxEp1RoVgpNsK5dfxkzjaizu7nyNhmTYCWh1VJWGQwnswCufDRFoVVm1jwgz3W8AkqpF8R2Rl4KGMpsnF7zevgMLibDQrQpg3uaLRsUrxKX9c1FqjL8+SdnS7I8Ne61SEAeNrUc8ZKHHwUcvmQosFP8juO8wiLLsLve0KzCl2hL/QD6Evnt7damjzD6wRLafw3SqBMPr/4tvlkHjSwNlh/vKKFUceeaqOCx2w5H4dxS6wrdQHBdre/kKin80B8iLsvAAABx2Gr1aWgEjBPFiZwHJID1GtRVzz42uJ0LSm9u6c6nJAXVL/lrcnSikrnVg3IB6EBG4/XjtsZZpGLhvIy+KHjgOeBqlm4Lby2gbRVnOS1M7QFCNuuptTxTGwRT/spYjO5KMM+CB9xERMVzQnVXosBXokJJ7J+QwsHIXxr+4ml2pD1rSBwExiz0KMPJ1iWBPcUXmheiTHciWG202iJQc1ZW+sT6ceUeIMceDT6VQVUz6F+CUmoAFwqxugma4bIhzwXT9wkr0431wGPCo74K8qh2t9ESMjKZsYPCAp7f7KK0jEp4awT0gTquWZJfLX4kmyGq9UrNFiGjhn/CGKE1NoaX1KzXIlbgPwp8MrtLibk7gcSEr8YC+0b0hXdaEpV8OhFQlUhnYPf08DiL4eb"
PERSIST_ROOT = "{\"account\":\"{\\\"isAuthenticated\\\":true,\\\"firstName\\\":\\\"Joel\\\",\\\"lastName\\\":\\\"McKinney\\\",\\\"userID\\\":\\\"c4f1d19d-76fc-473f-8925-80886d0bfbb5\\\",\\\"email\\\":\\\"fly386@gmail.com\\\",\\\"isBatsAccountLinked\\\":false,\\\"registrationDate\\\":\\\"2025-01-17T16:58:25.085Z\\\",\\\"bestSubscription\\\":null,\\\"highestAccessLevel\\\":null,\\\"isFreeTrialEligible\\\":true}\",\"_persist\":\"{\\\"version\\\":25,\\\"rehydrated\\\":true}\"}"

COOKIES = [
    {"domain": "gc.com", "expires": 1807359794, "name": "afUserId", "path": "/", "sameSite": "Lax", "secure": False, "value": "725bcac6-3ded-4fdc-a6b2-d028641bb124-p"},
    {"domain": "gc.com", "expires": 1775388038, "name": "gc_logged_in", "path": "/", "sameSite": "Lax", "secure": False, "value": "1"},
    # Add other critical session cookies if needed
]

# Construct Playwright storage state
storage_state = {
    "cookies": COOKIES,
    "origins": [
      {
        "origin": "https://web.gc.com",
        "localStorage": [
          { "name": "eden-auth-tokens", "value": EDEN_AUTH_TOKENS },
          { "name": "persist:root", "value": PERSIST_ROOT }
        ]
      }
    ]
}

# Ensure directory exists
output_path = Path("h:/Repos/Personal/Softball/data/auth.json")
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w") as f:
    json.dump(storage_state, f, indent=2)

print(f"Successfully created {output_path}")
