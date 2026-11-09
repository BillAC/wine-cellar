import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
import models
import auth
import crud
from database import Base
from email_service import EMAIL_LOG_FILE


class MultiUserTests(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "CELLAR_USERNAME": "cellar",
                "CELLAR_PASSWORD": "TestPassword123!",
                "CELLAR_SESSION_SECRET": "test-signing-secret-at-least-32-chars-long",
                "WINE_APP_BASE_URL": "http://cellar.example:8000",
            },
            clear=True,
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

        # Seed admin user
        self.admin = models.User(
            username="cellar",
            email="cellar@local",
            hashed_password=auth.hash_password("TestPassword123!"),
            role=models.UserRole.ADMIN,
            status=models.UserStatus.APPROVED,
        )
        self.session.add(self.admin)
        self.session.commit()

        if os.path.exists(EMAIL_LOG_FILE):
            try:
                os.remove(EMAIL_LOG_FILE)
            except OSError:
                pass

    def tearDown(self):
        if os.path.exists(EMAIL_LOG_FILE):
            try:
                os.remove(EMAIL_LOG_FILE)
            except OSError:
                pass

    def test_request_access_creates_pending_user(self):
        req = main.UserRequestAccess(
            username="william",
            email="william@example.com",
            password="Password1234",
        )
        resp = main.request_access_endpoint(req, db=self.session)
        self.assertEqual(resp["status"], "pending")
        self.assertEqual(resp["username"], "william")

        user = self.session.query(models.User).filter_by(username="william").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.status, models.UserStatus.PENDING)
        self.assertEqual(user.role, models.UserRole.USER)
        self.assertTrue(auth.verify_password("Password1234", user.hashed_password))

    def test_request_access_validations(self):
        # Invalid email
        with self.assertRaises(HTTPException) as cm:
            main.request_access_endpoint(
                main.UserRequestAccess(
                    username="bademail",
                    email="not-an-email",
                    password="Password1234",
                ),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 422)

        # Reserved root admin name
        with self.assertRaises(HTTPException) as cm:
            main.request_access_endpoint(
                main.UserRequestAccess(
                    username="cellar",
                    email="admin@example.com",
                    password="Password1234",
                ),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 409)

        # Create valid user first
        main.request_access_endpoint(
            main.UserRequestAccess(
                username="william",
                email="william@example.com",
                password="Password1234",
            ),
            db=self.session,
        )

        # Duplicate username
        with self.assertRaises(HTTPException) as cm:
            main.request_access_endpoint(
                main.UserRequestAccess(
                    username="william",
                    email="different@example.com",
                    password="Password1234",
                ),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 409)

        # Duplicate email
        with self.assertRaises(HTTPException) as cm:
            main.request_access_endpoint(
                main.UserRequestAccess(
                    username="someoneelse",
                    email="william@example.com",
                    password="Password1234",
                ),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 409)

    def test_admin_approves_and_rejects_user(self):
        # 1. Request access
        main.request_access_endpoint(
            main.UserRequestAccess(
                username="rita",
                email="rita@example.com",
                password="Password1234",
            ),
            db=self.session,
        )
        user = self.session.query(models.User).filter_by(username="rita").first()
        self.assertEqual(user.status, models.UserStatus.PENDING)

        # 2. Approve
        approved = main.approve_user_endpoint(user.id, db=self.session)
        self.assertEqual(approved.status, models.UserStatus.APPROVED)
        self.assertIsNotNone(approved.approved_at)

        # Verify email logged
        self.assertTrue(os.path.exists(EMAIL_LOG_FILE))
        with open(EMAIL_LOG_FILE, "r") as f:
            content = f.read()
            self.assertIn("rita@example.com", content)
            self.assertIn("Cellar Access Approved", content)

        # 3. Another user requested and rejected
        main.request_access_endpoint(
            main.UserRequestAccess(
                username="intruder",
                email="intruder@example.com",
                password="Password1234",
            ),
            db=self.session,
        )
        user2 = self.session.query(models.User).filter_by(username="intruder").first()
        rejected = main.reject_user_endpoint(user2.id, db=self.session)
        self.assertEqual(rejected.status, models.UserStatus.REJECTED)

    def test_login_flow(self):
        # 1. Request access
        main.request_access_endpoint(
            main.UserRequestAccess(
                username="magali",
                email="magali@example.com",
                password="Password1234",
            ),
            db=self.session,
        )

        # Pending user cannot login
        with self.assertRaises(HTTPException) as cm:
            main.login(
                main.LoginRequest(username="magali", password="Password1234"),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("pending approval", cm.exception.detail)

        # Wrong password returns 401
        with self.assertRaises(HTTPException) as cm:
            main.login(
                main.LoginRequest(username="cellar", password="WrongPassword"),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 401)

        # Root admin login succeeds
        admin_login = main.login(
            main.LoginRequest(username="cellar", password="TestPassword123!"),
            db=self.session,
        )
        self.assertEqual(admin_login.status_code, 200)

        # Approve magali
        user = self.session.query(models.User).filter_by(username="magali").first()
        main.approve_user_endpoint(user.id, db=self.session)

        # Now magali login succeeds
        user_login = main.login(
            main.LoginRequest(username="magali", password="Password1234"),
            db=self.session,
        )
        self.assertEqual(user_login.status_code, 200)

        # Can also login via email
        email_login = main.login(
            main.LoginRequest(username="magali@example.com", password="Password1234"),
            db=self.session,
        )
        self.assertEqual(email_login.status_code, 200)

        # Deactivate user -> 403
        user.status = models.UserStatus.DISABLED
        self.session.commit()
        with self.assertRaises(HTTPException) as cm:
            main.login(
                main.LoginRequest(username="magali", password="Password1234"),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("deactivated", cm.exception.detail)

    def test_forgot_and_reset_password(self):
        # 1. Register & approve
        main.request_access_endpoint(
            main.UserRequestAccess(
                username="alex",
                email="alex@example.com",
                password="OldPassword123",
            ),
            db=self.session,
        )
        user = self.session.query(models.User).filter_by(username="alex").first()
        main.approve_user_endpoint(user.id, db=self.session)

        # 2. Forgot password request
        forgot_resp = main.forgot_password_endpoint(
            main.ForgotPasswordRequest(identifier="alex@example.com"),
            db=self.session,
        )
        self.assertIn("message", forgot_resp)

        token_rec = (
            self.session.query(models.PasswordResetToken)
            .join(models.User)
            .filter(models.User.username == "alex")
            .first()
        )
        self.assertIsNotNone(token_rec)
        self.assertFalse(token_rec.used)
        reset_token = token_rec.token

        # 3. Reset password
        reset_resp = main.reset_password_endpoint(
            main.ResetPasswordRequest(token=reset_token, new_password="NewPassword456"),
            db=self.session,
        )
        self.assertIn("Password updated successfully", reset_resp["message"])

        # Token is now used
        self.session.refresh(token_rec)
        self.assertTrue(token_rec.used)

        # Trying to reuse token raises 400
        with self.assertRaises(HTTPException) as cm:
            main.reset_password_endpoint(
                main.ResetPasswordRequest(token=reset_token, new_password="AnotherPassword"),
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 400)

        # Old password rejected, new password accepted
        with self.assertRaises(HTTPException) as cm:
            main.login(main.LoginRequest(username="alex", password="OldPassword123"), db=self.session)
        self.assertEqual(cm.exception.status_code, 401)

        ok_login = main.login(main.LoginRequest(username="alex", password="NewPassword456"), db=self.session)
        self.assertEqual(ok_login.status_code, 200)

    def test_admin_cannot_alter_or_delete_root_admin(self):
        admin_id = self.admin.id
        mock_req = MagicMock()
        admin_token = auth.create_session_token("cellar", role="admin")
        mock_req.cookies.get.return_value = admin_token

        # Cannot disable self
        with self.assertRaises(HTTPException) as cm:
            main.update_user_status_endpoint(
                admin_id,
                main.UserStatusUpdate(status=models.UserStatus.DISABLED),
                request=mock_req,
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 400)

        # Cannot demote root admin
        with self.assertRaises(HTTPException) as cm:
            main.update_user_role_endpoint(
                admin_id,
                main.UserRoleUpdate(role=models.UserRole.USER),
                request=mock_req,
                db=self.session,
            )
        self.assertEqual(cm.exception.status_code, 400)

        # Cannot delete root admin
        with self.assertRaises(HTTPException) as cm:
            main.delete_user_endpoint(admin_id, request=mock_req, db=self.session)
        self.assertEqual(cm.exception.status_code, 400)

    def test_admin_only_operations(self):
        admin_req = MagicMock()
        admin_req.cookies.get.return_value = auth.create_session_token("cellar", role="admin")

        user_req = MagicMock()
        user_req.cookies.get.return_value = auth.create_session_token("william", role="user")

        # 1. Location creation
        loc_payload = main.LocationBase(name="Reserve Rack")
        with self.assertRaises(HTTPException) as cm:
            main.create_location_endpoint(loc_payload, self.session, http_request=user_req)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Admin privileges required", cm.exception.detail)

        loc = main.create_location_endpoint(loc_payload, self.session, http_request=admin_req)
        self.assertEqual(loc.name, "Reserve Rack")

        # 2. Location update
        update_payload = main.LocationUpdate(name="Main Reserve Rack")
        with self.assertRaises(HTTPException) as cm:
            main.update_location_endpoint(loc.id, update_payload, self.session, http_request=user_req)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Admin privileges required", cm.exception.detail)

        updated_loc = main.update_location_endpoint(loc.id, update_payload, self.session, http_request=admin_req)
        self.assertEqual(updated_loc.name, "Main Reserve Rack")

        # 3. Wine deletion
        crud.create_wine(self.session, {"qr_id": "WINE-ADMIN-01", "location_id": loc.id, "name": "Test Wine"})

        with self.assertRaises(HTTPException) as cm:
            main.delete_wine_endpoint("WINE-ADMIN-01", self.session, http_request=user_req)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Admin privileges required", cm.exception.detail)

        # 4. Location deletion (blocked for regular user)
        with self.assertRaises(HTTPException) as cm:
            main.delete_location_endpoint(loc.id, self.session, http_request=user_req)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Admin privileges required", cm.exception.detail)

        # Admin can delete wine
        del_resp = main.delete_wine_endpoint("WINE-ADMIN-01", self.session, http_request=admin_req)
        self.assertEqual(del_resp, {"deleted": "WINE-ADMIN-01"})

        # Now location is empty, admin can delete location
        del_loc_resp = main.delete_location_endpoint(loc.id, self.session, http_request=admin_req)
        self.assertIsNone(del_loc_resp)
        self.assertIsNone(self.session.get(models.Location, loc.id))

    def test_admin_batch_delete_wine(self):
        admin_req = MagicMock()
        admin_req.cookies.get.return_value = auth.create_session_token("cellar", role="admin")

        user_req = MagicMock()
        user_req.cookies.get.return_value = auth.create_session_token("william", role="user")

        # Create 3 bottles in a batch
        crud.create_wine(self.session, {"qr_id": "BATCH-01", "name": "Batch Cabernet"})
        crud.create_wine(self.session, {"qr_id": "BATCH-02", "name": "Batch Cabernet"})
        crud.create_wine(self.session, {"qr_id": "BATCH-03", "name": "Batch Cabernet"})

        payload = main.WineBatchDelete(qr_ids=["BATCH-01", "BATCH-02", "BATCH-03"])

        # Non-admin rejected with 403
        with self.assertRaises(HTTPException) as cm:
            main.delete_wine_batch_endpoint(payload, self.session, http_request=user_req)
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("Admin privileges required", cm.exception.detail)

        # Admin succeeds
        res = main.delete_wine_batch_endpoint(payload, self.session, http_request=admin_req)
        self.assertEqual(res["count"], 3)
        self.assertEqual(sorted(res["deleted"]), ["BATCH-01", "BATCH-02", "BATCH-03"])

        # Verify bottles deleted from DB
        remaining = self.session.query(models.WineEntry).filter(
            models.WineEntry.qr_id.in_(["BATCH-01", "BATCH-02", "BATCH-03"])
        ).all()
        self.assertEqual(len(remaining), 0)

        # Deleting non-existent bottles returns 404
        with self.assertRaises(HTTPException) as cm:
            main.delete_wine_batch_endpoint(payload, self.session, http_request=admin_req)
        self.assertEqual(cm.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
