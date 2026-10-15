Automatic website visual context
===============================

The orchestrator dispatches website research through ToolRegistry. A visual companion runs alongside passive REA, browser reconnaissance, discovery manifests/navigation intents, and public API operations. Browser navigation captures the resulting page after navigation settles. Nested automation requests use this same registry hook.

Each request shares a twelve-picture collector and one labeled PDF, queued automatically for the next Copilot message. Samples include the actual current viewport, visible button/navigation closeups, and middle/end scrolling views when possible. Only a separately owned guarded revisit is scrolled during REA analysis, so the analysis page keeps its position. Revisit pictures are labeled explicitly because transient application state may differ. Crawl4AI captures each actual crawl-owned page before closing it, preserving its extracted HTML before visual scrolling. Existing browser.discover state screenshots supply its visual companion without a duplicate batch.

Visual context is sampled evidence: it does not establish complete site, control, or page coverage. The twelve-picture limit can leave later pages unpictured and is reported. A missing matching owned browser page, capture error, attachment size limit, or full attachment batch is recorded without changing the investigation outcome. Public API origins must match the available owned browser page; unrelated browser pages are never substituted. File-analysis pictures are labeled browser context and are not evidence that the analyzed file originated there.

Artifacts are retained below the session screenshots directory. Credentials in password controls are masked using the existing capture mask. Existing browser ownership, origin checks, and execution approval remain authoritative. New-chat cancellation cancels visual tasks and closes their independently owned revisit tabs.
