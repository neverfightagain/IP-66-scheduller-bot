import unittest
from datetime import date
from attestation_radar import calculate_semester_week, analyze_attestation_status, format_attestation_report

class TestAttestationRadar(unittest.TestCase):
    def test_semester_week_calculation(self):
        # 1 вересня 2026 -> 1-й тиждень
        d_start = date(2026, 9, 1)
        sem_start = calculate_semester_week(d_start)
        self.assertEqual(sem_start["current_week"], 1)
        self.assertEqual(sem_start["target_attestation"], 1)

        # 20 жовтня 2026 (приблизно 8-й тиждень)
        d_oct = date(2026, 10, 20)
        sem_oct = calculate_semester_week(d_oct)
        self.assertEqual(sem_oct["current_week"], 8)
        self.assertEqual(sem_oct["weeks_to_att1"], 0)

        # 20 листопада 2026 (12-й тиждень -> ціль 2-га атестація)
        d_nov = date(2026, 11, 20)
        sem_nov = calculate_semester_week(d_nov)
        self.assertEqual(sem_nov["target_attestation"], 2)

    def test_analyze_attestation_zones(self):
        cur_date = date(2026, 10, 18)
        assignments = [
            # АСД: 2 прострочені роботи -> Червона зона
            {"course_id": "АСД", "title": "Лаба 1", "due_date": "2026-10-01"},
            {"course_id": "АСД", "title": "Лаба 2", "due_date": "2026-10-10"},
            # КДМ: 1 прострочена -> Жовта зона
            {"course_id": "КДМ", "title": "Лаба 1", "due_date": "2026-10-05"},
            # Мережі: майбутній дедлайн -> Зелена зона
            {"course_id": "Мережі", "title": "Лаба 1", "due_date": "2026-10-25"},
        ]

        analysis = analyze_attestation_status(assignments, attestation_num=1, current_date=cur_date)

        self.assertIn("Мережі", analysis["green_zone"])
        yellow_courses = [c[0] for c in analysis["yellow_zone"]]
        self.assertIn("КДМ", yellow_courses)
        red_courses = [c[0] for c in analysis["red_zone"]]
        self.assertIn("АСД", red_courses)

    def test_report_formatting(self):
        analysis = {
            "attestation_num": 1,
            "semester_info": {"current_week": 7, "weeks_to_att1": 1, "weeks_to_att2": 7},
            "green_zone": ["Мережі"],
            "yellow_zone": [("КДМ", {"overdue": 1})],
            "red_zone": [("АСД", {"overdue": 2})],
            "total_subjects": 3
        }
        text, kb = format_attestation_report(analysis)

        self.assertIn("АТЕСТАЦІЙНИЙ РАДАР ГРУПИ", text)
        self.assertIn("Критична зона ризику", text)
        self.assertIn("АСД", text)
        self.assertIsNotNone(kb)


if __name__ == "__main__":
    unittest.main()
