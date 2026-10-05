"""Stable global transaction-lock namespace; never reuse a key across resources.

42 source storage; 43 memory index; 44 skills; 45 tasks; 46 task execution
(two-key session locks); 47 artifact storage. Keep deployed identifiers stable.
"""

MEMORY_INDEX = 791103043
ARTIFACT_STORAGE = 791103047
