"""Pure intent/instruction tests: no browser, files, network or execution."""
import unittest

from copilot_agent.delivery import OFFICE_EXTENSIONS, detect_requirements, delivery_requirements, delivery_instruction, retry_message


class DeliveryRequirementTests(unittest.TestCase):
    def test_exact_read_only_reporting_recovery_does_not_trigger_artifact_delivery(self):
        request = ('Report the already completed execution from the attached actual local report. '
                   'Include stdout download-run-test and exit 0, and state that it used the restricted interpreter. '
                   'Do not request tools or a new download; do not execute the source again. '
                   'The earlier once grant is consumed. This is a read-only reporting recovery, '
                   'not a request to generate or deliver a file.')
        self.assertEqual('none', detect_requirements(request).mode)
        self.assertEqual([], delivery_requirements(request)['expected_names'])
        self.assertEqual('', delivery_instruction(request))

    def test_explicit_negated_creation_and_delivery_requests_are_not_outputs(self):
        requests = [
            'Do not create report.txt.',
            "Don't generate report.xlsx or deliver notes.md.",
            'Don’t create a complete Python project.',
            'Never provide a downloadable file or ZIP archive.',
            'This is not a request to generate or deliver a file.',
            'There is no request to create report.txt.',
            'Report the prior result; do not create report.txt or produce report.docx.',
            'Report completed output from result.txt; never package multiple files.',
            'Report result.txt. Do not request another download.',
        ]
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual('none', detect_requirements(request).mode)
                self.assertEqual('', delivery_instruction(request))

    def test_positive_output_clauses_remain_after_report_or_separate_prohibitions(self):
        requests = [
            'Report prior result and create report.txt.',
            'Report prior result. Do not download the old package; create report.txt.',
            'Do not create report.xlsx; create report.txt.',
            "Don't generate old.docx, but create report.txt.",
            'Never create a complete project. Instead create report.txt.',
            'Create report.txt; do not create old.xlsx or deliver other.md.',
            'Create report.txt and do not generate extra.docx.',
            'Create report.txt; never deliver but.docx.',
            'Do not generate "but extra.docx"; create report.txt.',
        ]
        for request in requests:
            with self.subTest(request=request):
                result=detect_requirements(request)
                self.assertEqual('direct', result.mode)
                self.assertEqual(('report.txt',), result.expected_names)
        self.assertEqual('zip', detect_requirements('Do not create notes.txt; generate report.xlsx.').mode)
        result=detect_requirements('Never create old.docx. Create report.txt and notes.md.')
        self.assertEqual('zip', result.mode)
        self.assertEqual(('report.txt','notes.md'), result.expected_names)

    def test_negation_words_in_filenames_are_data_not_instructions(self):
        for filename in ('never.txt', '"Never generate.md"', '"Do not create.txt"'):
            with self.subTest(filename=filename):
                result=detect_requirements('Create '+filename+'.')
                self.assertEqual('direct', result.mode)
                self.assertEqual((filename.strip('"'),), result.expected_names)
        self.assertEqual('none', detect_requirements('report.txt').mode)

    def test_existing_code_execution_and_filenames_do_not_request_downloads(self):
        requests = [
            'Run synthetic-download-run.py.',
            'Execute the already downloaded source.py and save output.xlsx locally.',
            'Run the extracted scripts from the downloaded project package.',
            'Request exactly one code_runner call using the downloaded synthetic-download-run.py bytes. After its actual outcome report stdout and exit code.',
            'Report the completed execution of synthetic-download-run.py. Do not request another download.',
            'Run "Create output.py".',
            'Request exactly one code_runner call. Arguments:\n{"script": "print(\'create downloadable file\')"}',
        ]
        for request in requests:
            with self.subTest(request=request):
                self.assertEqual('none', detect_requirements(request).mode)
        self.assertEqual('direct', detect_requirements('Create synthetic-download-run.py and then run it.').mode)
        self.assertEqual('direct', detect_requirements('Run existing input.py and provide a downloadable report.txt.').mode)

    def test_all_supported_office_variants_always_zip(self):
        for extension in OFFICE_EXTENSIONS:
            with self.subTest(extension=extension):
                result = detect_requirements('Create report.' + extension)
                self.assertEqual('zip', result.mode)
                self.assertEqual(('report.' + extension,), result.expected_names)

    def test_office_without_explicit_filename_and_package_requests_zip(self):
        for text in ('Create an Excel workbook.', 'Prepare a Word document.', 'Make a PowerPoint presentation.',
                     'Create a .xlsx file.', 'Generate an XLSX workbook.', 'Prepare a Word report.',
                     'Build a full Python project.', 'Provide the complete source code package.',
                     'Create a software project.', 'Build a new project.', 'Create multiple files.',
                     'Generate report.docx and notes.md.', 'Make an archive package.'):
            with self.subTest(text=text):
                self.assertEqual('zip', detect_requirements(text).mode)

    def test_single_nonoffice_files_require_direct_download(self):
        for extension in ('py', 'md', 'txt', 'json', 'csv', 'pdf', 'html', 'js'):
            with self.subTest(extension=extension):
                result = detect_requirements('Please create result.' + extension)
                self.assertEqual('direct', result.mode)
                self.assertEqual(('result.' + extension,), result.expected_names)
        self.assertEqual({'mode': 'direct', 'expected_names': ['synthetic.txt'],
                          'reason': detect_requirements('Create one synthetic text file named synthetic.txt').reason},
                         delivery_requirements('Create one synthetic text file named synthetic.txt'))

    def test_multiple_mixed_nonoffice_outputs_are_zip(self):
        result = detect_requirements('Create app.py, README.md and settings.json.')
        self.assertEqual('zip', result.mode)
        self.assertEqual(('app.py', 'README.md', 'settings.json'), result.expected_names)

    def test_known_names_preserve_quoted_spaces_and_deduplicate_case(self):
        result = detect_requirements('Create "Project notes.md" and refer to "project NOTES.md" again.')
        self.assertEqual('direct', result.mode)
        self.assertEqual(('Project notes.md',), result.expected_names)

    def test_clearly_named_input_file_is_not_an_output(self):
        result = detect_requirements('Read existing source.csv and create report.txt.')
        self.assertEqual('direct', result.mode)
        self.assertEqual(('report.txt',), result.expected_names)
        result = detect_requirements('Read existing source.xlsx and create parser.py.')
        self.assertEqual('direct', result.mode)
        self.assertEqual(('parser.py',), result.expected_names)

    def test_project_plan_is_not_a_complete_coding_project(self):
        result = detect_requirements('Create a project plan.md.')
        self.assertEqual('direct', result.mode)
        self.assertEqual(('plan.md',), result.expected_names)

    def test_informational_read_only_and_plain_conversation_need_no_delivery(self):
        for text in ('', 'Hello.', 'Explain report.docx.', 'Read existing script.py.',
                     'How do I create report.docx?', 'What is a ZIP archive?',
                     'Write a short greeting.', 'List the filenames README.md and app.py.',
                     'Inspect synthetic file.', 'What is a coding project?', 'Explain this project.'):
            with self.subTest(text=text):
                self.assertEqual('none', detect_requirements(text).mode)
                self.assertEqual('', delivery_instruction(text))

    def test_instruction_requires_outside_envelope_actual_link_and_zip_fallback(self):
        text = delivery_instruction('Create script.py.')
        self.assertIn('AFTER <<<COPILOT_AGENT_V1_END>>>', text)
        self.assertIn('outside the JSON object', text)
        self.assertIn('downloadable ZIP', text)
        self.assertIn('sandbox', text)
        self.assertIn('script.py', text)
        self.assertIn('do not execute', text)

    def test_office_instruction_keeps_original_format_inside_zip(self):
        text = delivery_instruction('Generate model.xlsx.')
        self.assertIn('even a single Office file must be inside ZIP', text)
        self.assertIn('model.xlsx', text)
        self.assertIn('actual clickable Markdown', text)

    def test_requirements_dictionary_uses_plain_json_compatible_names(self):
        self.assertEqual({'mode': 'direct', 'expected_names': ['output.txt'],
                          'reason': detect_requirements('Create output.txt').reason},
                         detect_requirements('Create output.txt').as_dict())
        self.assertEqual(detect_requirements('Create output.txt').as_dict(), delivery_requirements('Create output.txt'))

    def test_nonstring_input_is_rejected(self):
        with self.assertRaises(TypeError):
            detect_requirements(None)


class DeliveryRetryTests(unittest.TestCase):
    def test_exact_retry_budget_then_no_retry(self):
        for attempt in range(1, 4):
            text = retry_message('No actual downloadable UI link was observed.', attempt)
            self.assertIn(f'{attempt}/3', text)
            self.assertIn('same requested artifact', text)
            self.assertIn('AFTER <<<COPILOT_AGENT_V1_END>>>', text)
        self.assertEqual('', retry_message('No link.', 4))
        self.assertEqual('', retry_message('No link.', 100))
        self.assertEqual('', retry_message('No link.', 1, max_attempts=0))

    def test_office_retry_never_falls_back_to_plaintext(self):
        text = retry_message('Only an Office preview was returned.', 1, office=True)
        self.assertIn('Office outputs must remain inside a downloadable ZIP', text)
        self.assertIn('do not substitute plaintext', text)

    def test_retry_remains_an_ordinary_counted_conversation_message(self):
        text = retry_message('Sandbox-only reference.', 1)
        self.assertIn('ordinary conversation submission', text)
        self.assertIn('normal counting/attachment rules', text)
        self.assertIn('do not invent', text.lower())

    def test_invalid_retry_arguments_fail_before_building_instruction(self):
        for kwargs in ({'reason': '', 'attempt': 1}, {'reason': 'Missing link', 'attempt': -1},
                       {'reason': 'Missing link', 'attempt': 0},
                       {'reason': 'Missing link', 'attempt': True},
                       {'reason': 'Missing link', 'attempt': 1, 'max_attempts': -1},
                       {'reason': 'Missing link', 'attempt': 1, 'office': 'yes'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                retry_message(**kwargs)
