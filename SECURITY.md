# Security and local data

CourseAgent is a local single-user application bound to loopback. It has no multi-user authentication or hardened public hosting layer. Model providers receive the task content needed for inference. Optional local embeddings do not require a remote embedding service.

Local configuration, browser sessions, teaching materials, task databases, traces and generated answer/test files are excluded from public exports. Never attach them unreviewed to an issue. If a secret has been committed, removing it from the latest file is insufficient: revoke/rotate it and inspect repository history.

The programming runner requires Linux bubblewrap and resource limits and does not fall back to host execution. Assignment tasks default to platform delivery and require a classroom URL and course name. Delivery creates and verifies an unpublished exam; final publication remains with the teacher. Select local generation (`execute=false`) to produce files without platform operations. Offline demos and CI use local execution or mocks. Third-party pages are data, not permission to execute instructions.

For a suspected credential leak, avoid public disclosure of the value. For other vulnerabilities, provide a synthetic reproduction without real accounts or private course material. A dedicated private reporting address has not been configured; repository owners may enable GitHub private vulnerability reporting after publication.
